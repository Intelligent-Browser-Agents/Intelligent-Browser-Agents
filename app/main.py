"""
FastAPI application for DOM Q&A service.

This module provides the REST API endpoint for answering questions about DOM content.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from core.models import AnswerRequest, AnswerResponse
from core.pipeline import answer
from core.qa import qa_init
from core.config import load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for application startup and shutdown.
    Initializes components on startup.
    """
    # Startup
    config = load_config()
    model_name = config.get("qa", {}).get("model_name", "distilbert-base-cased-distilled-squad")
    qa_init(model_name=model_name)
    print(f"QA pipeline initialized with model: {model_name}")
    
    yield
    
    # Shutdown (if needed in the future)
    pass


app = FastAPI(
    title="DOM Q&A API",
    description="Question-answering service for DOM content",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "DOM Q&A API"}


@app.post("/answer", response_model=AnswerResponse)
async def answer_endpoint(request: AnswerRequest) -> AnswerResponse:
    """
    Answer a question about DOM content.
    
    Args:
        request: AnswerRequest containing DOM HTML and prompt/question
        
    Returns:
        AnswerResponse with answer, confidence, and source information
        
    Raises:
        HTTPException: If DOM or prompt is empty, DOM is too large, or processing fails
    """
    # Pydantic validation already ensures dom and prompt are non-empty
    # Now check DOM size (configurable limit)
    config = load_config()
    max_dom_size_mb = config.get("api", {}).get("max_dom_size_mb", 10)
    
    dom_size_bytes = len(request.dom.encode('utf-8'))
    dom_size_mb = dom_size_bytes / (1024 * 1024)
    
    if dom_size_mb > max_dom_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"DOM content too large: {dom_size_mb:.2f}MB (max {max_dom_size_mb}MB)"
        )
    
    try:
        # Call pipeline to get answer
        response = answer(request.dom, request.prompt)
        return response
    except Exception as e:
        # Log the error and return a generic error message
        print(f"Error processing answer: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the request"
        )

