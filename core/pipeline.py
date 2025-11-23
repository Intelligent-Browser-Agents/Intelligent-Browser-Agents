"""
Pipeline orchestration for DOM Q&A.

This module wires together all components: parse → retrieve → QA → score → response.
"""

from core.dom_parser import parse_dom
from core.retrieval import retrieve
from core.qa import qa_over_top_k
from core.scoring import blend, apply_span_sanity_checks, apply_abstain, should_abstain_on_retriever_score, should_abstain_on_raw_score, should_abstain_on_low_spread
from core.config import load_config
from core.qa import qa_extract
from core.models import AnswerResponse, SourceInfo


def _extract_source_snippet(chunk_text: str, start: int, end: int, window: int = 50) -> str:
    """
    Extract a snippet from chunk text with a window around the answer span.
    
    Args:
        chunk_text: Full text of the chunk
        start: Start character index of the answer
        end: End character index of the answer
        window: Number of characters to include before and after (default 50)
        
    Returns:
        Text snippet with window around the answer, normalized whitespace
    """
    # Ensure indices are valid
    text_len = len(chunk_text)
    start = max(0, min(start, text_len))
    end = max(start, min(end, text_len))
    
    # Calculate snippet boundaries with window
    snippet_start = max(0, start - window)
    snippet_end = min(text_len, end + window)
    
    # Extract snippet
    snippet = chunk_text[snippet_start:snippet_end]
    
    # Normalize whitespace (replace multiple spaces/newlines with single space)
    import re
    snippet = re.sub(r'\s+', ' ', snippet)
    snippet = snippet.strip()
    
    return snippet


def answer(dom: str, prompt: str) -> AnswerResponse:
    """
    Main pipeline function: parse DOM, retrieve chunks, extract answer, score, and return response.
    
    Args:
        dom: HTML string to parse
        prompt: User question/prompt
        
    Returns:
        AnswerResponse with answer, confidence, and source information
    """
    # Step 1: Parse DOM into chunks
    chunks = parse_dom(dom)
    
    # If no chunks, return empty response
    if not chunks:
        return AnswerResponse(
            answer="",
            confidence=0.0,
            source=SourceInfo(text_snippet="")
        )
    
    # Step 2: Retrieve top-K chunks
    retrieved, all_scores_equal, max_raw_score = retrieve(chunks, prompt)
    
    # If no retrieved chunks, return empty response
    if not retrieved:
        return AnswerResponse(
            answer="",
            confidence=0.0,
            source=SourceInfo(text_snippet="")
        )
    
    # Step 2.5: Check if all raw BM25 scores were equal (indicates no match)
    # This happens when a garbage question doesn't match any content
    if all_scores_equal:
        return AnswerResponse(
            answer="",
            confidence=0.0,
            source=SourceInfo(text_snippet="")
        )
    
    # Step 2.6: Check if max raw BM25 score is too low (indicates poor match)
    # This catches garbage queries that have high normalized scores but low raw scores
    # due to common words matching (e.g., "is", "the", "of")
    if should_abstain_on_raw_score(max_raw_score):
        return AnswerResponse(
            answer="",
            confidence=0.0,
            source=SourceInfo(text_snippet="")
        )
    
    # Step 2.7: Check if retriever score spread is too low (no clear winner)
    # This catches garbage queries that pass individual thresholds but have no clear winner
    # Only applies when raw_score is in suspicious range (0.85-1.0) to avoid catching legitimate queries
    if len(retrieved) >= 2:
        top_retriever_score = retrieved[0][1]  # Normalized score of top chunk
        second_retriever_score = retrieved[1][1]  # Normalized score of second chunk
        
        # Load suspicious_min from config
        config = load_config()
        scoring_config = config.get("scoring", {})
        suspicious_min = scoring_config.get("raw_score_suspicious_min", 0.85)
        
        if should_abstain_on_low_spread(max_raw_score, top_retriever_score, second_retriever_score, suspicious_min=suspicious_min):
            return AnswerResponse(
                answer="",
                confidence=0.0,
                source=SourceInfo(text_snippet="")
            )
    
    # Step 3: Evaluate QA on top-K chunks and get best one
    best_result = qa_over_top_k(retrieved, prompt)
    
    if best_result is None:
        return AnswerResponse(
            answer="",
            confidence=0.0,
            source=SourceInfo(text_snippet="")
        )
    
    best_chunk, qa_result = best_result
    
    # Get retriever score for this chunk
    retriever_score = next((score for chunk, score in retrieved if chunk.id == best_chunk.id), 0.0)
    
    # Step 3.3: Check if we should prioritize retriever score over QA score
    # If the top retriever score chunk has significantly higher retriever score than the selected chunk,
    # use the top retriever score chunk instead (retriever ranking is more reliable)
    if len(retrieved) > 1:
        # Get the top retriever score chunk (first in retrieved list, which is sorted by retriever score)
        top_retriever_chunk, top_retriever_score = retrieved[0]
        
        # Check if the difference is significant
        config = load_config()
        scoring_config = config.get("scoring", {})
        difference_threshold = scoring_config.get("retriever_score_difference_threshold", 0.3)
        
        # If top retriever chunk is different and has significantly higher score, use it instead
        if (top_retriever_chunk.id != best_chunk.id and 
            top_retriever_score - retriever_score > difference_threshold):
            # Re-run QA on the top retriever chunk
            top_qa_result = qa_extract(prompt, top_retriever_chunk.text)
            if top_qa_result is not None:
                best_chunk = top_retriever_chunk
                qa_result = top_qa_result
                retriever_score = top_retriever_score
    
    # Step 3.5: Check retriever score - if too low, abstain immediately
    # This prevents QA from overriding a low retriever score with a high QA score
    if should_abstain_on_retriever_score(retriever_score):
        return AnswerResponse(
            answer="",
            confidence=retriever_score,  # Use retriever score as confidence
            source=SourceInfo(text_snippet="")
        )
    
    # Step 4: Blend retriever and QA scores
    blended_confidence = blend(retriever_score, qa_result["score"])
    
    # Step 5: Apply span sanity checks
    after_span_check = apply_span_sanity_checks(blended_confidence, qa_result["answer"])
    
    # Step 6: Apply abstain logic
    final_answer, final_confidence = apply_abstain(after_span_check, qa_result["answer"])
    
    # Step 7: Extract source snippet with window around answer
    source_snippet = _extract_source_snippet(
        best_chunk.text,
        qa_result["start"],
        qa_result["end"],
        window=50
    )
    
    # Build response
    return AnswerResponse(
        answer=final_answer,
        confidence=final_confidence,
        source=SourceInfo(
            node_id=best_chunk.node_id,
            xpath=best_chunk.xpath,
            text_snippet=source_snippet
        )
    )

