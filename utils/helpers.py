from pythainlp.tokenize import word_tokenize
from pythainlp.util import normalize
from pythainlp.corpus import thai_stopwords
import unicodedata
import re

def preprocess_text(text: str) -> str:
    """ประมวลผลข้อความก่อนบันทึกลงฐานข้อมูล"""
    # Normalize ข้อความด้วย pythainlp.util.normalize
    text = normalize(text)
    # รวม Unicode NFC เพื่อให้สระและวรรณยุกต์ถูกต้อง
    text = unicodedata.normalize('NFC', text)
    # เก็บตัวอักษรไทย, อังกฤษ, ตัวเลข, และอักขระพิเศษที่อนุญาต (วงเล็บ, /, -, ²)
    text = re.sub(r'[^\u0E00-\u0E7Fa-zA-Z0-9\s\(\)/\-\u00B2]', ' ', text)
    # ลบช่องว่างซ้ำ
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

def extract_keywords(text: str) -> list:
    """แยกคำสำคัญจากข้อความ"""
    # Normalize ข้อความ
    text = normalize(text)
    text = unicodedata.normalize('NFC', text)
    
    # ตัดคำภาษาไทยด้วย pythainlp
    thai_words = word_tokenize(text, engine="newmm")
    
    # ตัดคำภาษาอังกฤษและเก็บตัวเลขในบริบท (เช่น 10-20)
    # อนุญาตคำที่มีเครื่องหมายพิเศษ เช่น (10-20), มิลลิลิตร./กิโลกรัม
    special_patterns = re.findall(r'\b(?:\d+\-\d+|[a-zA-Z]+(?:\'[a-zA-Z]+)?|[\(\)\u00B2\/\-])\b', text)
    
    # รวมคำทั้งหมด
    words = [word.strip().lower() for word in thai_words + special_patterns if word.strip()]
    
    # Stopwords
    thai_stops = set(thai_stopwords())
    english_stops = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
        'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'were', 'will',
        'with', 'have', 'had', 'do', 'does', 'did', 'but', 'or', 'what', 'when', 'where',
        'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such'
    }
    stopwords = thai_stops.union(english_stops).union({"และ", "กับ", "ใน", "ที่", "แห่ง", "เป็น", "ให้", "ได้", "ๆ"})
    
    # กรองคำ
    keywords = [
        word for word in words
        if word not in stopwords and
        len(word) > 1 or word in {'(', ')', '/', '-', '²'}  # อนุญาตอักขระพิเศษ
    ]
    
    # ลบคำซ้ำและเรียงลำดับ
    return sorted(list(set(keywords)))