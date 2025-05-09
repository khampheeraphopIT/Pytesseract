import re
from pythainlp.tokenize import word_tokenize
from pythainlp.corpus import thai_stopwords

def preprocess_text(text: str) -> str:
    # ลบเครื่องหมายวรรคตอนและช่องว่างซ้ำ
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

def extract_keywords(text: str) -> list:
    # ตัดคำภาษาไทยด้วย pythainlp
    thai_words = word_tokenize(text, engine="newmm")
    # ตัดคำภาษาอังกฤษ
    english_words = re.findall(r'[a-zA-Z][a-zA-Z0-9]*', text)
    words = thai_words + english_words
    
    # ใช้ stopwords จาก pythainlp และเพิ่มคำภาษาอังกฤษ
    stopwords = set(thai_stopwords()).union({"and", "with", "in", "at"})
    
    # กรองคำ
    keywords = [
        word.lower() for word in words
        if word.lower() not in stopwords and
        len(word) > 1 and
        not re.match(r'^\d+$', word)
    ]
    
    # ลบคำซ้ำ
    return list(set(keywords))