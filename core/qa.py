"""
Question-answering pipeline utilities.

This module manages a singleton instance of the Hugging Face
question-answering pipeline to avoid repeatedly loading heavy models.
"""

from __future__ import annotations

from typing import Any

from transformers import pipeline

from core.config import load_config
from core.dom_parser import Chunk
from core.scoring import blend

_QA_PIPELINE = None
_QA_MODEL_NAME: str | None = None


def qa_init(model_name: str | None = None, force_reload: bool = False):
    """
    Initialize (or retrieve) the QA pipeline singleton.

    Args:
        model_name: Optional Hugging Face model name. Defaults to config value.
        force_reload: Force reloading the pipeline even if already initialized.

    Returns:
        Hugging Face QA pipeline instance.
    """
    global _QA_PIPELINE, _QA_MODEL_NAME

    if model_name is None:
        config = load_config()
        model_name = config.get("qa", {}).get("model_name", "distilbert-base-cased-distilled-squad")

    if force_reload or _QA_PIPELINE is None or model_name != _QA_MODEL_NAME:
        _QA_PIPELINE = pipeline("question-answering", model=model_name)
        _QA_MODEL_NAME = model_name

    return _QA_PIPELINE


def get_qa_pipeline():
    """
    Convenience accessor for the QA pipeline.

    Returns:
        QA pipeline (initializing it if necessary).
    """
    return qa_init()


def reset_qa_pipeline():
    """
    Reset QA pipeline cache (primarily for tests).
    """
    global _QA_PIPELINE, _QA_MODEL_NAME
    _QA_PIPELINE = None
    _QA_MODEL_NAME = None


def qa_extract(question: str, context: str) -> dict[str, Any]:
    """
    Extract answer from context using QA pipeline.
    
    Args:
        question: The question to answer
        context: The context text to search for the answer
        
    Returns:
        Dictionary with keys:
            - answer: Extracted answer text
            - score: Confidence score in [0, 1]
            - start: Start character index in context
            - end: End character index in context
    """
    # Get QA pipeline (initializes if needed)
    qa_pipeline = get_qa_pipeline()
    
    # Run QA pipeline
    result = qa_pipeline(question=question, context=context)
    
    # Map to our output format
    # The pipeline returns: {'answer': str, 'score': float, 'start': int, 'end': int}
    # Score is already a probability in [0, 1] from the model
    return {
        "answer": result["answer"],
        "score": float(result["score"]),  # Ensure it's a float
        "start": int(result["start"]),
        "end": int(result["end"])
    }


def qa_over_top_k(chunks_with_scores: list[tuple[Chunk, float]], question: str) -> tuple[Chunk, dict[str, Any]] | None:
    """
    Evaluate QA on each retrieved chunk and return the best one.
    Uses blended score (retriever + QA) to select the best chunk.
    
    Args:
        chunks_with_scores: List of (Chunk, retriever_score) tuples from retrieval
        question: The question to answer
        
    Returns:
        Tuple of (best_chunk, qa_result) where qa_result contains answer, score, start, end.
        Returns None if no chunks provided.
    """
    if not chunks_with_scores:
        return None
    
    best_chunk = None
    best_qa_result = None
    best_combined_score = -1.0
    
    # Evaluate QA on each chunk
    for chunk, retriever_score in chunks_with_scores:
        # Run QA extraction on this chunk
        qa_result = qa_extract(question, chunk.text)
        
        # Blend retriever and QA scores
        combined_score = blend(retriever_score, qa_result["score"])
        
        # Keep track of the chunk with the highest combined score
        if combined_score > best_combined_score:
            best_combined_score = combined_score
            best_chunk = chunk
            best_qa_result = qa_result
    
    if best_chunk is None:
        return None
    
    return (best_chunk, best_qa_result)

