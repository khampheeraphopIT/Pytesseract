import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from core.pdf_extractor import PDFTextExtractor
from api.schemas import UploadResponse, SearchResponse, SearchRequest
from typing import List
import os

router = APIRouter()
extractor = PDFTextExtractor()

@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    print(f"Uploading file: {file.filename}")
    if not file.filename.endswith(".pdf"):
        print("Invalid file type, only PDF allowed")
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        print(f"Temporary file created at: {tmp_path}")
        # ดึงข้อความจาก PDF
        extracted_text = extractor.extract_text_from_pdf(tmp_path)
        # บันทึกไป Elasticsearch
        extractor.save_to_database(tmp_path, file.filename)
        os.remove(tmp_path)
        print(f"File {file.filename} processed and temporary file removed")
        return UploadResponse(
            id="TBD",
            title=file.filename,
            message="File uploaded successfully",
            extracted_text=extracted_text
        )
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@router.post("/search", response_model=List[SearchResponse])
async def search_documents(request: SearchRequest):
    print(f"Searching with query: {request.query}")
    try:
        results = extractor.search_documents(request.query, request.min_score)
        print(f"Found {len(results)} results")
        return [SearchResponse(**result) for result in results]
    except Exception as e:
        print(f"Error searching documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching documents: {str(e)}")