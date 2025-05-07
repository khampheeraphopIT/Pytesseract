import os
import pytesseract
from PyPDF2 import PdfReader
from PIL import Image
import io
from elasticsearch import Elasticsearch
import re
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class PDFTextExtractor:
    def __init__(self):
        self.es = Elasticsearch(
            os.getenv('ELASTICSEARCH_HOSTS', 'http://localhost:9200'),
            basic_auth=(
                os.getenv('ELASTICSEARCH_USERNAME', 'elastic'), 
                os.getenv('ELASTICSEARCH_PASSWORD', '')
            )
        )
        self.index_name = os.getenv('ELASTICSEARCH_INDEX', 'documents')
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

    def preprocess_text(self, text):
        return text.strip()

    def extract_keywords(self, text):
        words = re.findall(r'[\u0E00-\u0E7F]+|[a-zA-Z][a-zA-Z0-9]*', text)
        stopwords = ["และ", "กับ", "ใน", "ที่", "แห่ง", "เป็น", "ให้", "ได้", "ๆ", "and", "with", "in", "at"]
        keywords = [
            word.lower() for word in words 
            if word.lower() not in stopwords and 
               len(word) > 1 and 
               not re.match(r'^\d+$', word)
        ]
        return list(set(keywords))

    def save_to_database(self, file_path, title=None):
        if title is None:
            title = os.path.basename(file_path)
        try:
            search_query = {"query": {"term": {"file_path": file_path}}}
            res = self.es.search(index=self.index_name, body=search_query, size=1000)
            for hit in res['hits']['hits']:
                self.es.delete(index=self.index_name, id=hit['_id'])
            
            full_text = self.extract_text_from_pdf(file_path)
            pages = re.split(r'Page \d+:', full_text)
            pages_content = []
            all_keywords = set()
            
            for page_num, page_text in enumerate(pages[1:], start=1):
                normalized_text = self.preprocess_text(page_text)
                keywords = self.extract_keywords(normalized_text)
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

    def search_documents(self, query, min_score=0.5):
        try:
            search_query = {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": [
                                        "title^2",
                                        "title.english^2",
                                        "pages.normalized_text",
                                        "pages.normalized_text.english",
                                        "all_keywords^1.5",
                                        "pages.keywords"
                                    ]
                                }
                            },
                            {
                                "prefix": {
                                    "all_keywords": {
                                        "value": query.lower()
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
                        "title.english": {},
                        "pages.normalized_text": {},
                        "pages.normalized_text.english": {},
                        "all_keywords": {}
                    }
                }
            }
            res = self.es.search(index=self.index_name, body=search_query)
            results = []
            seen_ids = set()
            for hit in res['hits']['hits']:
                doc_id = hit["_id"]
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                matched_terms = set()
                if 'highlight' in hit:
                    for field, highlights in hit['highlight'].items():
                        for hl in highlights:
                            terms = re.findall(r'<em>(.*?)</em>', hl)
                            matched_terms.update(terms)
                results.append({
                    "id": doc_id,
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

if __name__ == "__main__":
    extractor = None
    try:
        extractor = PDFTextExtractor()
        pdf_path = "test.pdf" 
        if not os.path.exists(pdf_path):
            print(f"File {pdf_path} not found")
            exit(1)
        extractor.save_to_database(pdf_path)
        
        search_query = "Mining"
        print(f"\nทดสอบค้นหาด้วยคีย์เวิร์ด: {search_query}")
        results = extractor.search_documents(search_query)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if extractor is not None:
            extractor.close()