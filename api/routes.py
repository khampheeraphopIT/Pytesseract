import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from config.settings import settings
from fastapi.responses import FileResponse
from core.pdf_extractor import PDFTextExtractor
from api.schemas import UploadResponse, SearchForm, SearchRequest
from typing import List
router = APIRouter()
extractor = PDFTextExtractor()

# กำหนดโฟลเดอร์สำหรับเก็บไฟล์ PDF
UPLOAD_DIR = "./uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    try:
        # บันทึกไฟล์ใน UPLOAD_DIR
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
        
        extracted_text = extractor.extract_text_from_pdf(file_path)
        document = extractor.save_to_database(file_path, file.filename)
        
        if document is None:
            raise HTTPException(status_code=500, detail="Error saving document to database")
        
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

@router.get("/download/{doc_id}")
async def download_file(doc_id: str):
    try:
        doc = extractor.es.get(index=extractor.index_name, id=doc_id)["_source"]
        file_path = doc["file_path"]
        file_name = doc["title"]
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(file_path, filename=file_name, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")