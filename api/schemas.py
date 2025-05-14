from pydantic import BaseModel
from typing import List, Dict, Optional

class UploadResponse(BaseModel):
    id: str
    title: str
    message: str
    extracted_text: Optional[str] = None

class SearchForm(BaseModel):
    id: str
    title: str
    score: float
    matched_terms: List[str]
    highlight: Dict[str, List[str]]

class SearchRequest(BaseModel):
    query: str
    min_score: Optional[float] = 0.1