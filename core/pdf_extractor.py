import os
import io
import re
from datetime import datetime

# Third-party
from elasticsearch import Elasticsearch
import pytesseract
from PyPDF2 import PdfReader
from PIL import Image
import pdf2image

# Local
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
                        "title": {
                            "type": "text",
                            "analyzer": "thai",
                            "fields": {
                                "english": {"type": "text", "analyzer": "english"}
                            }
                        },
                        "file_path": {"type": "keyword"},
                        "upload_date": {"type": "date"},
                        "pages": {
                            "type": "nested",
                            "properties": {
                                "page_number": {"type": "integer"},
                                "original_text": {
                                    "type": "text",
                                    "analyzer": "thai",
                                    "fields": {
                                        "english": {"type": "text", "analyzer": "english"}
                                    }
                                },
                                "normalized_text": {
                                    "type": "text",
                                    "analyzer": "thai",
                                    "fields": {
                                        "english": {"type": "text", "analyzer": "english"}
                                    }
                                },
                                "keywords": {"type": "keyword"}
                            }
                        },
                        "all_keywords": {"type": "keyword"}
                    }
                },
                "settings": {
                    "analysis": {
                        "filter": {
                            "thai_stop": {
                                "type": "stop",
                                "stopwords": "_thai_"
                            },
                            "thai_folding": {
                                "type": "icu_folding"
                            },
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
                            "english": {
                                "type": "standard",
                                "filter": ["lowercase"]
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
                        images = self._convert_pdf_page_to_image(file_path, page_num)
                        for img in images:
                            page_text = pytesseract.image_to_string(img, lang='tha+eng')
                            text += f"\nPage {page_num} (OCR):\n{page_text}\n"
        except Exception as e:
            print(f"Error processing PDF: {e}")
        return text

    def _convert_pdf_page_to_image(self, file_path, page_num, dpi=300):
        try:
            # แปลงหน้า PDF เฉพาะหน้าที่ต้องการเป็นภาพ
            images = pdf2image.convert_from_path(
                file_path,
                dpi=dpi,
                first_page=page_num,
                last_page=page_num
            )
            return images
        except:
            # try:
            #     if '/XObject' in page['/Resources']:
            #         x_object = page['/Resources']['/XObject'].get_object()
            #         for obj in x_object:
            #             if x_object[obj]['/Subtype'] == '/Image':
            #                 img_data = x_object[obj].get_data()
            #                 img = Image.open(io.BytesIO(img_data))
            #                 return [img]
            # except:
            #     pass
            return []


    def save_to_database(self, file_path, title=None):
        if not self.es.indices.exists(index=self.index_name):
            print(f"Index '{self.index_name}' ไม่มีอยู่ กำลังสร้างใหม่...")
            self.create_index()
        
        if title is None:
            title = os.path.basename(file_path)
        try:
            # ลบเอกสารที่มี file_path เดียวกันก่อน
            self.es.delete_by_query(
                index=self.index_name,
                body={
                    "query": {
                        "term": {
                            "file_path": file_path
                        }
                    }
                }
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
                    "keywords": keywords
                })

            document = {
                "title": title,
                "file_path": file_path,
                "upload_date": datetime.now().isoformat(),
                "pages": pages_content,
                "all_keywords": list(all_keywords)
            }
            res = self.es.index(index=self.index_name, body=document)
            print(f"Document saved to Elasticsearch with ID: {res['_id']}")
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}")

    def search_documents(self, query, min_score=0.1):
        try:
            # แยกคำค้นจาก query (เช่น "เทคนิค การใช้งาน การทำงาน" -> ["เทคนิค", "การใช้งาน", "การทำงาน"])
            query_terms = [term.strip() for term in query.split() if term.strip()]
            if not query_terms:
                print("Query not found")
                return []

            should_clauses = []
            for term in query_terms:
                should_clauses.append({
                    "multi_match": {
                        "query": term,
                        "fields": [
                            "title^2",
                            "title.english^2",
                            "pages.normalized_text",
                            "pages.normalized_text.english",
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
                "query": { # query.bool.should รวมเงื่อนไขทั้งหมด
                    "bool": {
                        "should": should_clauses,
                        "minimum_should_match": 1
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "title.english": {},
                        "pages.normalized_text": {},
                        "pages.normalized_text.english": {},
                        "all_keywords": {},
                    },
                    "encoder": "html"
                }
            }
            res = self.es.search(index=self.index_name, body=search_query)

            results = []
            seen_titles = set()
            for hit in res['hits']['hits']:
                doc_title = hit["_source"]["title"]
                
                if doc_title in seen_titles:
                    continue
                seen_titles.add(doc_title)
                matched_terms = set()
                if 'highlight' in hit:
                    for highlights in hit['highlight'].values():
                        for hl in highlights:
                            terms = re.findall(r'<em>(.*?)</em>', hl)
                            matched_terms.update(terms)
                
                results.append({
                    "id": hit["_id"],
                    "title": hit["_source"]["title"],
                    "score": hit["_score"],
                    "matched_terms": list(matched_terms),
                    "highlight": hit.get('highlight', {})
                })
                
            print(f"กำลังค้นหาคำว่า: {query}")
            
            if results:
                print(f"พบเอกสาร: {len(results)} ")
                for r in results:
                    print(f"Title: {r['title']}")
                    highlight = r.get('highlight', {})
                    for field, hls in highlight.items():
                        for hl in hls:
                            clean_hl = re.sub(r'</?em>', '', hl)
                            print(f"- {field}: {clean_hl}")
            else:
                print(f"ไม่พบผล: {query}")
                docs = self.es.search(index=self.index_name, body={"query": {"match_all": {}}})
                print("เอกสารใน index:")
                for doc in docs['hits']['hits']:
                    print(f"- {doc['_source']['title']}")
            return results
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการค้นหา: {e}")
            return []

    def close(self):
        self.es.close()