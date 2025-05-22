import os
import re
from datetime import datetime
from elasticsearch import Elasticsearch
import pytesseract
from PyPDF2 import PdfReader
from PIL import ImageEnhance, ImageFilter
from PIL import Image
import cv2
import numpy as np
import pdf2image
from config.settings import settings
from utils.helpers import preprocess_text, extract_keywords

class PDFTextExtractor:
    def __init__(self):
        self.es = Elasticsearch(
            "http://localhost:9200",
            basic_auth=(settings.ELASTICSEARCH_USERNAME, settings.ELASTICSEARCH_PASSWORD)
        )
        if not self.es.ping():
            raise ConnectionError("Cannot connect to Elasticsearch")
        self.index_name = settings.ELASTICSEARCH_INDEX
        self.create_index()

    def create_index(self):
        if not self.es.indices.exists(index=self.index_name):
            mapping = {
                "mappings": {
                    "properties": {
                        "title": {"type": "text", "analyzer": "standard"},
                        "file_path": {"type": "keyword"},
                        "upload_date": {"type": "date"},
                        "pages": {
                            "type": "nested",
                            "properties": {
                                "page_number": {"type": "integer"},
                                "original_text": {"type": "text", "analyzer": "standard"},
                                "normalized_text": {"type": "text", "analyzer": "thai"},
                                "keywords": {"type": "keyword"}
                            }
                        },
                        "all_keywords": {"type": "keyword"}
                    }
                },
                "settings": {
                    "analysis": {
                        "filter": {
                            "thai_stop": {"type": "stop", "stopwords": "_thai_"},
                            "english_stop": {"type": "stop", "stopwords": "_english_"},
                            "thai_folding": {"type": "icu_folding"},
                            "edge_ngram_filter": {
                                "type": "edge_ngram",
                                "min_gram": 2,
                                "max_gram": 10
                            }
                        },
                        "analyzer": {
                            "thai": {
                                "tokenizer": "icu_tokenizer",
                                "filter": [
                                    "thai_stop",
                                    "thai_folding",
                                    "lowercase",
                                    "edge_ngram_filter"
                                ]
                            },
                            "standard": {
                                "tokenizer": "standard",
                                "filter": [
                                    "english_stop",
                                    "lowercase",
                                    "edge_ngram_filter"
                                ]
                            }
                        }
                    }
                }
            }
            self.es.indices.create(index=self.index_name, body=mapping)

    def extract_text_from_pdf(self, file_path):
        text = ""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                for page_num, page in enumerate(pdf_reader.pages, start=1):
                    page_text = page.extract_text()
                    if page_text.strip():
                        text += f"\nPage {page_num}:\n{page_text}\n"
                    else:
                        images = self._convert_pdf_page_to_image(file_path, page_num, dpi=400)
                        for img in images:
                            img = img.convert('L')
                            img = ImageEnhance.Contrast(img).enhance(2.0)
                            img = img.filter(ImageFilter.SHARPEN)
                            page_text = pytesseract.image_to_string(img, lang='tha+eng', config='--psm 6')
                            text += f"\nPage {page_num} (OCR):\n{page_text}\n"
        except Exception as e:
            print(f"Error processing PDF: {e}")
        return text

    def _convert_pdf_page_to_image(self, file_path, page_num, dpi=600):
        try:
            images = pdf2image.convert_from_path(
                file_path,
                dpi=dpi,
                first_page=page_num,
                last_page=page_num
            )
            processed_images = []
            for img in images:
                img_array = np.array(img)
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
                thresh = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 3
                )
                img = Image.fromarray(thresh)
                img = ImageEnhance.Contrast(img).enhance(2.0)
                img = img.filter(ImageFilter.SHARPEN)
                processed_images.append(img)
            return processed_images
        except:
            return []

    def save_to_database(self, file_path, title=None):
        if not self.es.indices.exists(index=self.index_name):
            print(f"Index '{self.index_name}' does not exist, creating new...")
            self.create_index()
        
        if title is None:
            title = os.path.basename(file_path)
        try:
            self.es.delete_by_query(
                index=self.index_name,
                body={"query": {"term": {"file_path": file_path}}}
            )

            full_text = self.extract_text_from_pdf(file_path)
            pages = re.split(r'Page \d+:', full_text)
            pages_content = []
            all_keywords = set()

            for page_num, page_text in enumerate(pages[1:], start=1):
                normalized_text = preprocess_text(page_text)
                keywords = extract_keywords(normalized_text)
                all_keywords.update(keywords)
                pages_content.append({
                    "page_number": page_num,
                    "original_text": page_text,
                    "normalized_text": normalized_text,
                    "keywords": list(set(keywords))
                })

            document = {
                "title": title,
                "file_path": file_path,
                "upload_date": datetime.now(),
                "pages": pages_content,
                "all_keywords": list(all_keywords)
            }
            res = self.es.index(index=self.index_name, body=document)
            document["_id"] = res["_id"]
            return document
        except Exception as e:
            print(f"Error saving document: {e}")
            return None

    def search_documents(self, query, min_score=0):
        try:
            query_terms = [term.strip() for term in query.split() if term.strip()]
            if not query_terms:
                print("Query not found")
                return []

            exact_clauses = []
            fuzzy_clauses = []
            for term in query_terms:
                exact_clauses.append({
                    "multi_match": {
                        "query": term,
                        "fields": [
                            "title^2",
                            "pages.normalized_text",
                            "all_keywords^1.5",
                            "pages.keywords"
                        ],
                        "type": "best_fields",
                        "tie_breaker": 0.3
                    }
                })
                fuzzy_clauses.append({
                    "multi_match": {
                        "query": term,
                        "fields": [
                            "title^2",
                            "pages.normalized_text",
                            "all_keywords^1.5",
                            "pages.keywords"
                        ],
                        "type": "best_fields",
                        "tie_breaker": 0.3,
                        "fuzziness": "AUTO",
                        "prefix_length": 1
                    }
                })

            search_query = {
                "query": {
                    "bool": {
                        "should": [
                            {"bool": {"should": exact_clauses, "minimum_should_match": 1}},
                            {"bool": {"should": fuzzy_clauses, "minimum_should_match": 1}},
                            {
                                "nested": {
                                    "path": "pages",
                                    "query": {
                                        "bool": {
                                            "should": [
                                                {"bool": {"should": exact_clauses, "minimum_should_match": 1}},
                                                {"bool": {"should": fuzzy_clauses, "minimum_should_match": 1}}
                                            ],
                                            "minimum_should_match": 1
                                        }
                                    },
                                    "inner_hits": {
                                        "name": "pages",
                                        "size": 100,
                                        "highlight": {
                                            "fields": {
                                                "pages.normalized_text": {
                                                    "fragment_size": 0,
                                                    "number_of_fragments": 0
                                                },
                                                "pages.keywords": {}
                                            },
                                            "encoder": "html"
                                        }
                                    }
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "pages.normalized_text": {
                            "fragment_size": 0,
                            "number_of_fragments": 0
                        },
                        "all_keywords": {},
                        "pages.keywords": {}
                    },
                    "encoder": "html"
                },
                "min_score": min_score
            }

            res = self.es.search(index=self.index_name, body=search_query)
            results = []
            seen_titles = set()
            for hit in res['hits']['hits']:
                doc_title = hit["_source"]["title"]
                if doc_title in seen_titles:
                    continue
                seen_titles.add(doc_title)

                matched_terms = {"exact": set(), "fuzzy": set()}
                if 'highlight' in hit:
                    for highlights in hit['highlight'].values():
                        for hl in highlights:
                            terms = re.findall(r'<em>(.*?)</em>', hl)
                            for term in terms:
                                if any(t.lower() == term.lower() for t in query_terms):
                                    matched_terms["exact"].add(term)
                                else:
                                    matched_terms["fuzzy"].add(term)

                matched_pages = []
                if 'inner_hits' in hit and 'pages' in hit['inner_hits']:
                    for inner_hit in hit['inner_hits']['pages']['hits']['hits']:
                        page_highlights = inner_hit.get("highlight", {})
                        exact_match_counts = {}
                        for term in matched_terms["exact"]:
                            count = 0
                            for highlights in page_highlights.values():
                                for hl in highlights:
                                    count += len(re.findall(rf'<em>{re.escape(term)}</em>', hl))
                            if count > 0:
                                exact_match_counts[term] = count

                        matched_pages.append({
                            "page_number": int(inner_hit["_source"]["page_number"]),
                            "highlight": {k: [str(v) for v in val] for k, val in page_highlights.items()},
                            "exact_match_counts": exact_match_counts,
                            "keywords": inner_hit["_source"].get("keywords", [])  # เพิ่ม keywords
                        })

                results.append({
                    "id": hit["_id"],
                    "title": hit["_source"]["title"],
                    "score": hit["_score"],
                    "query": query,
                    "matched_terms": {
                        "exact": list(matched_terms["exact"]),
                        "fuzzy": list(matched_terms["fuzzy"])
                    },
                    "highlight": hit.get('highlight', {}),
                    "all_keywords": hit["_source"].get("all_keywords", []),
                    "matched_pages": matched_pages
                })

            print(f"Searching for: {query}")
            if results:
                print(f"Found {len(results)} documents")
                for r in results:
                    print(f"Title: {r['title']}")
                    print(f"Score: {r['score']}")
                    print(f"Exact Matches: {r['matched_terms']['exact']}")
                    print(f"Fuzzy Matches: {r['matched_terms']['fuzzy']}")
                    print(f"Matched Pages: {[p['page_number'] for p in r['matched_pages']]}")
            else:
                print(f"No results for: {query}")

            return results
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def close(self):
        self.es.close()