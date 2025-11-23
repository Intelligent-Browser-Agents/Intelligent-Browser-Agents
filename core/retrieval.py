from typing import List, Tuple
from rank_bm25 import BM25Okapi
import numpy as np
from core.dom_parser import Chunk
from core.config import load_config


def _tokenize(text: str) -> List[str]:
    """
    Simple tokenizer: lowercase and split on whitespace.
    
    Args:
        text: Text to tokenize
        
    Returns:
        List of tokens
    """
    return text.lower().split()


def fit_bm25(chunks: List[Chunk]) -> BM25Okapi:
    """
    Build a BM25 index from chunks.
    
    Args:
        chunks: List of Chunk objects to index
        
    Returns:
        BM25Okapi retriever instance
    """
    # Extract text from chunks and tokenize
    tokenized_corpus = [_tokenize(chunk.text) for chunk in chunks]
    
    # Create and return BM25 index
    bm25 = BM25Okapi(tokenized_corpus)
    return bm25


def retrieve(chunks: List[Chunk], prompt: str, top_k: int | None = None) -> tuple[List[Tuple[Chunk, float]], bool, float]:
    """
    Retrieve top-K chunks for a given prompt using BM25.
    
    Args:
        chunks: List of Chunk objects to search
        prompt: Query string
        top_k: Number of top chunks to return
        
    Returns:
        Tuple of:
        - List of (Chunk, score) tuples, where score is normalized to [0, 1]
        - Boolean indicating if all raw BM25 scores were equal (True means no match)
        - Maximum raw BM25 score (for threshold checking)
    """
    if not chunks:
        return ([], False, 0.0)
    
    if top_k is None:
        config = load_config()
        top_k = config.get("retrieval", {}).get("top_k", 3)

    if top_k <= 0:
        return ([], False, 0.0)

    top_k = min(top_k, len(chunks))
    
    # Build BM25 index
    bm25 = fit_bm25(chunks)
    
    # Tokenize query
    tokenized_query = _tokenize(prompt)
    
    # Get raw BM25 scores
    scores = bm25.get_scores(tokenized_query)
    
    # Min-max normalize to [0, 1]
    if len(scores) == 0:
        return ([], False, 0.0)
    
    min_score = min(scores)
    max_score = max(scores)
    max_raw_score = max_score  # Store max raw score before normalization
    
    # Check if all scores are equal (within small epsilon to handle floating point issues)
    all_scores_equal = abs(max_score - min_score) < 1e-10
    
    if all_scores_equal:
        # All scores are the same, assign equal normalized scores
        normalized_scores = [1.0] * len(scores)
    else:
        # Normalize: (score - min) / (max - min)
        normalized_scores = [(score - min_score) / (max_score - min_score) for score in scores]
    
    # Get top-K indices
    top_indices = np.argsort(scores)[::-1][:top_k]
    
    # Return top-K chunks with normalized scores
    result = [(chunks[i], normalized_scores[i]) for i in top_indices]
    
    return (result, all_scores_equal, max_raw_score)

