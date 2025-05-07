import re

def preprocess_text(text: str) -> str:
    return text.strip()

def extract_keywords(text: str) -> list:
    words = re.findall(r'[\u0E00-\u0E7F]+|[a-zA-Z][a-zA-Z0-9]*', text)
    stopwords = ["และ", "กับ", "ใน", "ที่", "แห่ง", "เป็น", "ให้", "ได้", "ๆ", "and", "with", "in", "at"]
    keywords = [
        word.lower() for word in words 
        if word.lower() not in stopwords and 
        len(word) > 1 and 
        not re.match(r'^\d+$', word)
    ]
    return list(set(keywords))