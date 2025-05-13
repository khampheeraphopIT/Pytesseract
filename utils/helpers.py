import re
from pythainlp.tokenize import word_tokenize
from pythainlp.corpus import thai_stopwords
import unicodedata

def preprocess_text(text: str) -> str:
    text = unicodedata.normalize('NFC', text)
    # ลบตัวอักษรพิเศษ ยกเว้นไทย อังกฤษ ตัวเลข ช่องว่าง
    text = re.sub(r'[^\u0E00-\u0E7Fa-zA-Z0-9\s]', ' ', text)
    return text.strip().lower() 

def extract_keywords(text: str) -> list:
    text = unicodedata.normalize('NFC', text)
    # ตัดคำภาษาไทย
    thai_words = word_tokenize(text, engine="newmm")
    # ตัดคำภาษาอังกฤษ
    english_words = re.findall(r'[a-zA-Z]+', text)
    words = [word for word in thai_words + english_words if word]  # ลบคำว่าง
    
    # Stopwords
    stopwords = set(thai_stopwords()).union({"and", "with", "in", "at"})
    
    # กรองคำ
    keywords = [
        word.lower() for word in words
        if word.lower() not in stopwords and
        len(word) > 1 and
        not re.match(r'^\d+$', word)
    ]
    
    return list(set(keywords))