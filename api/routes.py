import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from core.pdf_extractor import PDFTextExtractor
from api.schemas import UploadResponse, SearchForm, SearchRequest
from typing import List
import os

router = APIRouter()
extractor = PDFTextExtractor()

@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        
        extracted_text = extractor.extract_text_from_pdf(tmp_path)
        
        document = extractor.save_to_database(tmp_path, file.filename)
        
        # ตรวจสอบว่า document ไม่เป็น None
        if document is None:
            raise HTTPException(status_code=500, detail="Error saving document to database")
        
        os.remove(tmp_path)
        return UploadResponse(
            id=document["_id"], 
            title=file.filename,
            message="File uploaded successfully",
            extracted_text=extracted_text
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@router.post("/search", response_model=List[SearchForm])
async def search_documents(request: SearchRequest):
    try:
        results = extractor.search_documents(request.query, request.min_score)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching documents: {str(e)}")