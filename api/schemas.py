from pydantic import BaseModel
from typing import List, Dict, Optional

class MatchedPage(BaseModel):
    page_number: int
    highlight: Dict[str, List[str]]
    exact_match_counts: Dict[str, int] = {}

class UploadResponse(BaseModel):
    id: str
    title: str
    message: str
    extracted_text: Optional[str] = None

class SearchForm(BaseModel):
    id: str
    title: str
    score: float
    query: str
    matched_terms: Dict[str, List[str]]
    highlight: Dict[str, List[str]]
    all_keywords: List[str] = []
    matched_pages: List[MatchedPage] = []

class SearchRequest(BaseModel):
    query: str
    min_score: Optional[float] = 0.1