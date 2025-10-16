## Step 1 — Receive Query → Normalize Task

This module implements the input normalization layer for the Contact Agent prototype.

### Objective

Transform messy, human-written queries such as:

"find 2025 contact info for Joe’s Lawncare in Orlando"

into a structured, validated task object that can be passed into the agent pipeline.

### Files Implemented

File Purpose
schemas/contact_lookup_task.py Defines ContactLookupTask Pydantic model and normalization logic
scripts/task_parser.py Test script for parsing and verifying extraction logic

### Logic Breakdown

Stage Description

1. Normalize Text Compresses spacing, trims punctuation, prepares lowercase for regex matching.
2. Extract Year Uses regex `\b(19|20
3. Extract Location Matches keywords “in” or “near” followed by city or region text.
4. Remove Noise Words Strips filler verbs like “find”, “get”, “fetch”, “contact info”, etc.
5. Reconstruct Company Name Returns cleaned company string suitable for search API queries.

### Example Input & Output

# Run example

python -m scripts.task_parser

Output

{
"company": "Joe's Lawncare",
"target_year": 2025,
"hint_url": null,
"location_hint": "Orlando"
}

### Design Tradeoffs & Findings

Option Consideration Decision
Regex extraction vs. NLP parsing Regex gives deterministic, transparent results for simple patterns; NLP would be overkill. ✅ Used regex for MVP
LLM pre-processing Could improve ambiguous phrasing (“find Joe Lawncare 25 contact”) but adds latency. ❌ Deferred until refinement
Field validation Used Pydantic for easy downstream schema serialization (JSON). ✅ Adopted
Location extraction Limited to one trailing phrase (“in Orlando”), adequate for MVP. ✅ Keep simple
Error handling Falls back to None for missing fields. ✅ Acceptable for early stage

### Test Coverage

Example cases include:

With year and location (Joe’s Lawncare in Orlando)

Without location (UCF Computer Science Department)

With alternate phrasing (BrightSmile Dental 2024 Tampa)

All return consistent JSON output.

### Next Step

Proceed to Step 2: Domain Finder Tool — resolving candidate websites for each normalized company query.
This will extend the agent chain:

Receive Query → Normalize → Domain Search → Contact Extraction → Verification
