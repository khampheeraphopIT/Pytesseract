from elasticsearch import Elasticsearch
from config.settings import settings
import os
import pytesseract
from PyPDF2 import PdfReader
from PIL import Image
import io
import re
from datetime import datetime
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
                            "fields": {"english": {"type": "text", "analyzer": "english"}}
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
                                    "fields": {"english": {"type": "text", "analyzer": "english"}}
                                },
                                "normalized_text": {
                                    "type": "text",
                                    "analyzer": "thai",
                                    "fields": {"english": {"type": "text", "analyzer": "english"}}
                                },
                                "keywords": {"type": "keyword"}
                            }
                        },
                        "all_keywords": {"type": "keyword"}
                    }
                },
                "settings": {
                    "analysis": {
                        "analyzer": {
                            "thai": {
                                "type": "custom",
                                "tokenizer": "thai",
                                "filter": ["lowercase"]
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
                        images = self._convert_pdf_page_to_image(page)
                        for img in images:
                            page_text = pytesseract.image_to_string(img, lang='tha+eng')
                            text += f"\nPage {page_num} (OCR):\n{page_text}\n"
        except Exception as e:
            print(f"Error processing PDF: {e}")
        return text

    def _convert_pdf_page_to_image(self, page, dpi=300):
        try:
            import pdf2image
            images = pdf2image.convert_from_bytes(
                page._create_pdf_stream().getvalue(),
                dpi=dpi
            )
            return images
        except:
            try:
                if '/XObject' in page['/Resources']:
                    x_object = page['/Resources']['/XObject'].get_object()
                    for obj in x_object:
                        if x_object[obj]['/Subtype'] == '/Image':
                            img_data = x_object[obj].get_data()
                            img = Image.open(io.BytesIO(img_data))
                            return [img]
            except:
                pass
            return []

    def save_to_database(self, file_path, title=None):
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
                print("ไม่มีคำค้นที่ถูกต้อง")
                return []

            # สร้าง query สำหรับแต่ละคำค้น
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
                        "tie_breaker": 0.3
                    }
                })
                should_clauses.append({
                    "prefix": {
                        "all_keywords": {
                            "value": term.lower()
                        }
                    }
                })

            # สร้าง search query
            search_query = {
                "query": {
                    "bool": {
                        "should": should_clauses,
                        "minimum_should_match": 1  # ต้องเจออย่างน้อย 1 คำ
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "title.english": {},
                        "pages.normalized_text": {},
                        "pages.normalized_text.english": {},
                        "all_keywords": {}
                    }
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
                    for field, highlights in hit['highlight'].items():
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
            filtered_results = [r for r in results if r['score'] >= min_score]
            if not filtered_results:
                print("ไม่พบผลลัพธ์ที่ตรงกับคำค้นหา")
            else:
                print("\nผลการค้นหา:")
                for result in filtered_results:
                    print(f"เอกสาร: {result['title']} (ID: {result['id']})")
                    print(f"คะแนน: {result['score']:.4f}")
                    print(f"คำที่ตรงกัน: {', '.join(result['matched_terms']) or 'ไม่มีคำที่ไฮไลต์'}")
                    if result['highlight']:
                        print("ตัวอย่างข้อความที่พบ:")
                        for field, highlights in result['highlight'].items():
                            for hl in highlights:
                                print(f" - {hl}")
                    print("-" * 50)
            return filtered_results
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการค้นหา: {e}")
            return []

    def close(self):
        self.es.close()