"""
Scoring utilities for combining retriever and QA scores.
"""

from core.config import load_config


def blend(retriever_score: float, qa_score: float, w_r: float | None = None, w_qa: float | None = None) -> float:
    """
    Blend retriever and QA scores into a single confidence score.
    
    Args:
        retriever_score: Retriever score in [0, 1]
        qa_score: QA score in [0, 1]
        w_r: Weight for retriever score. If None, loads from config (default 0.35)
        w_qa: Weight for QA score. If None, loads from config (default 0.65)
        
    Returns:
        Blended confidence score in [0, 1]
    """
    # Load weights from config if not provided
    if w_r is None or w_qa is None:
        config = load_config()
        scoring_config = config.get("scoring", {})
        if w_r is None:
            w_r = scoring_config.get("weight_retriever", 0.35)
        if w_qa is None:
            w_qa = scoring_config.get("weight_qa", 0.65)
    
    # Weighted sum
    confidence = w_r * retriever_score + w_qa * qa_score
    
    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, confidence))
    
    return confidence


def apply_span_sanity_checks(confidence: float, answer: str, penalty: float | None = None) -> float:
    """
    Apply penalties to confidence based on answer span length.
    
    Args:
        confidence: Current confidence score in [0, 1]
        answer: The answer text to check
        penalty: Penalty amount to apply. If None, loads from config (default 0.15)
        
    Returns:
        Adjusted confidence score in [0, 1]
    """
    # Load config values
    config = load_config()
    scoring_config = config.get("scoring", {})
    
    # Load penalty from config if not provided
    if penalty is None:
        penalty = scoring_config.get("span_penalty", 0.15)
    
    # Load min/max answer lengths from config
    min_chars = scoring_config.get("min_answer_chars", 2)
    max_chars = scoring_config.get("max_answer_chars", 200)
    
    answer_len = len(answer.strip())
    
    # Apply penalty if answer is too short or too long
    if answer_len < min_chars or answer_len > max_chars:
        confidence = max(0.0, confidence - penalty)
    
    return confidence


def should_abstain(confidence: float, threshold: float | None = None) -> bool:
    """
    Determine if we should abstain from answering based on confidence threshold.
    
    Args:
        confidence: Final confidence score in [0, 1]
        threshold: Confidence threshold. If None, loads from config (default 0.5)
        
    Returns:
        True if confidence is below threshold (should abstain), False otherwise
    """
    # Load threshold from config if not provided
    if threshold is None:
        config = load_config()
        scoring_config = config.get("scoring", {})
        threshold = scoring_config.get("abstain_threshold", 0.5)
    
    return confidence < threshold


def apply_abstain(confidence: float, answer: str, threshold: float | None = None) -> tuple[str, float]:
    """
    Apply abstain logic: return empty answer if confidence is below threshold.
    
    Args:
        confidence: Final confidence score in [0, 1]
        answer: The answer text
        threshold: Confidence threshold. If None, loads from config (default 0.5)
        
    Returns:
        Tuple of (answer, confidence). Answer will be empty string if abstaining.
    """
    if should_abstain(confidence, threshold):
        return ("", confidence)
    return (answer, confidence)


def should_abstain_on_retriever_score(retriever_score: float, threshold: float | None = None) -> bool:
    """
    Determine if we should abstain based on retriever score being too low.
    
    A low retriever score indicates the question doesn't match the content well,
    so we should abstain even if QA gives a high score.
    
    Args:
        retriever_score: Retriever score in [0, 1]
        threshold: Retriever score threshold. If None, loads from config (default 0.2)
        
    Returns:
        True if retriever_score is below threshold (should abstain), False otherwise
    """
    # Load threshold from config if not provided
    if threshold is None:
        config = load_config()
        scoring_config = config.get("scoring", {})
        threshold = scoring_config.get("retriever_abstain_threshold", 0.2)
    
    return retriever_score < threshold


def should_abstain_on_raw_score(max_raw_score: float, threshold: float | None = None) -> bool:
    """
    Determine if we should abstain based on raw BM25 score being too low.
    
    A low raw BM25 score indicates the query doesn't match any content well,
    even if normalized scores are high (due to common words matching).
    
    Args:
        max_raw_score: Maximum raw BM25 score from retrieval
        threshold: Raw score threshold. If None, loads from config (default 1.0)
        
    Returns:
        True if max_raw_score is below threshold (should abstain), False otherwise
    """
    # Load threshold from config if not provided
    if threshold is None:
        config = load_config()
        scoring_config = config.get("scoring", {})
        threshold = scoring_config.get("raw_score_threshold", 0.8)
    
    return max_raw_score < threshold


def should_abstain_on_low_spread(max_raw_score: float, top_retriever_score: float, second_retriever_score: float | None = None, raw_threshold: float | None = None, spread_threshold: float | None = None, suspicious_min: float | None = None) -> bool:
    """
    Determine if we should abstain based on low retriever score spread (no clear winner).
    
    This catches garbage queries that pass individual thresholds but have no clear winner.
    Only applies when raw_score is in suspicious range (e.g., 0.85-1.0) to avoid catching
    legitimate queries with good or very low raw scores.
    
    Args:
        max_raw_score: Maximum raw BM25 score from retrieval
        top_retriever_score: Top normalized retriever score
        second_retriever_score: Second normalized retriever score (None if only one chunk)
        raw_threshold: Raw score threshold. If None, loads from config (default 1.0)
        spread_threshold: Spread threshold. If None, loads from config (default 0.15)
        suspicious_min: Minimum raw score to start checking spread. If None, loads from config (default 0.85)
        
    Returns:
        True if raw_score is in suspicious range AND spread is too small (should abstain), False otherwise
    """
    # Load thresholds from config if not provided
    if raw_threshold is None or spread_threshold is None or suspicious_min is None:
        config = load_config()
        scoring_config = config.get("scoring", {})
        if raw_threshold is None:
            # For this check, we use 1.0 as the threshold (not the config value)
            # because we want to catch queries with raw scores between suspicious_min-1.0
            raw_threshold = 1.0
        if spread_threshold is None:
            spread_threshold = scoring_config.get("retriever_score_spread_threshold", 0.15)
        if suspicious_min is None:
            suspicious_min = scoring_config.get("raw_score_suspicious_min", 0.85)
    
    # If only one chunk, can't calculate spread, so don't abstain based on spread
    if second_retriever_score is None:
        return False
    
    # Only check spread if raw_score is in suspicious range (suspicious_min <= max_raw_score < raw_threshold)
    # This way:
    # - Very low raw scores (< suspicious_min) are caught by raw_score_threshold check
    # - High raw scores (>= raw_threshold) don't need spread check
    # - Only medium raw scores (suspicious_min to raw_threshold) get spread check
    if max_raw_score < suspicious_min or max_raw_score >= raw_threshold:
        return False
    
    # Calculate spread (difference between top and second scores)
    spread = top_retriever_score - second_retriever_score
    
    # Abstain if: raw_score is in suspicious range AND spread < spread_threshold
    return spread < spread_threshold

