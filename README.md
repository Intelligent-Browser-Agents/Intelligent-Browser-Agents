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
Regex extraction vs. NLP parsing Regex gives deterministic, transparent results for simple patterns; NLP would be overkill. 
LLM pre-processing Could improve ambiguous phrasing (“find Joe Lawncare 25 contact”) but adds latency. 
Field validation Used Pydantic for easy downstream schema serialization (JSON). 
Location extraction Limited to one trailing phrase (“in Orlando”), adequate for MVP. 
Error handling Falls back to None for missing fields. 

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

## Step 2 — Domain Finder Tool → Resolve Candidate Websites

This step expands the Contact Agent prototype by taking the normalized company data from **Step 1**  
and automatically identifying the most likely **official domains** where contact and social information can later be extracted.

---

### Objective

Given a structured `ContactLookupTask` such as:

```
{
  "company": "Joe's Lawncare",
  "target_year": 2025,
  "hint_url": null,
  "location_hint": "Orlando"
}
```

the Domain Finder Tool queries external search APIs (SerpAPI / Bing) or offline dummy data to
produce a ranked list of probable official domains with relevance scores and rationale.

### Files Implemented

- schemas/domain_finder_models.py - Defines Pydantic I/O models for DomainFinderInput, DomainFinderOutput, DomainCandidate, and SearchResult.
- tools/search_providers.py - Implements the provider interface and adapters for SerpAPI (live) and DummyProvider (off-line testing).
- tools/domain_finder.py - Core search orchestration + scoring heuristics (token overlap, location matches, directory penalties).
- scripts/domain_finder_cli.py - Stand-alone CLI to test Step 2 in isolation using --company and --location arguments.
- scripts/contact_flow_cli.py - End-to-end glue for Step 1 → Step 2. Takes a raw prompt, normalizes it, and calls the domain finder automatically.

### Logic Breakdown

Stage Description

1. Search API Query Builds multiple queries such as "<company> official site", "<company> contact", and "<company> <location>".
2. Result Normalization Wraps raw search results in a uniform SearchResult schema (title, url, snippet, source).
3. Scoring & Ranking Heuristically scores results using token overlap between company name and title/URL, location hits, and penalties for directories (e.g., Yelp, Facebook).
4. Deduplication Keeps one result per unique domain to avoid repeated hosts.
5. Output Structuring Returns a DomainFinderOutput object with ranked DomainCandidate entries and reason strings.

Scoring Heuristics Summary

| Feature                  | Weight | Note                                        |
| ------------------------ | ------ | ------------------------------------------- |
| Title token overlap      | × 2.0  | Strong signal of official site              |
| URL token overlap        | × 2.0  | Checks domain and subdomain similarity      |
| Company token in URL     | + 1.0  | Direct boost for exact match                |
| Location hits            | + 0.5  | per token Boost when city/state appears     |
| Directory/Social domains | − 1.8  | Penalize aggregators (Yelp, Facebook, etc.) |
| Long or map paths        | − 0.3  | Discourages deep Google Maps links          |

### Example CLI Usage

Isolated Step 2 test

```
python -m scripts.domain_finder_cli --company "UCF Computer Science Department" --provider serpapi
```

End-to-end Step 1 → Step 2

```
python -m scripts.contact_flow_cli --query "find 2025 contact info for Shah's Halal in Orlando" --provider serpapi
```

Sample Output

```
TASK: {'company': "Shah's Halal", 'target_year': 2025, 'hint_url': None, 'location_hint': 'Orlando'}
CANDIDATES:
 1.79  https://www.shahshalalfood.com/orlando-fl/  [title_overlap=0.14, company_token_in_url, location_hits=1]
-1.30  https://www.instagram.com/p/DC9Qg1iOwPv/?hl=en  [location_hits=1, directory_penalty]
-1.51  https://www.yelp.com/biz/shahs-halal-food-orlando  [title_overlap=0.14, directory_penalty]
```

### Design Trade-offs & Findings

| **Option**                               | **Consideration**                                                                                                       | **Decision**                                               |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Search API vs. LLM domain guessing**   | API results are deterministic and verifiable; LLM guesses are non-deterministic.                                        | ✅ Use Search API (primary); LLM fallback later if needed. |
| **Scoring Heuristics vs. Model ranking** | Manual scoring is transparent and easy to tune.                                                                         | ✅ Manual for MVP.                                         |
| **SerpAPI integration**                  | Fast and reliable for Google-style results; requires API key setup via `.env`.                                          | ✅ Integrated with `python-dotenv`.                        |
| **LangGraph integration level**          | Keep Step 1 → Step 2 linked locally for POC; higher-level agent graph will orchestrate these steps in the final system. | ✅ Handled by future Overseer → Execution nodes.           |

## Integration with Step 1

contact_flow_cli.py demonstrates how the normalized output from ContactLookupTask feeds into DomainFinderInput.
This mirrors the Overseer → Execution handoff defined in the project’s architecture:

```
Overseer (Normalize) → Execution (Domain Finder) → Verification → Fallback → Finish
Later stages will plug into this same pattern as LangGraph nodes or chained LangChain Tools.
```

### Next Step

Proceed to Step 3 — Contact Extraction & Verification,
where the top-ranked domains will be fetched (Playwright / BeautifulSoup) and parsed for emails, phones, and social links.

---

## Step 3 — Contact Extraction & Verification

This step completes the Contact Agent POC by extracting structured contact information from the top-ranked domains identified in **Step 2**.

### Objective

Given a domain candidate like `https://www.example.com/`, this module:

1. Fetches the webpage using Playwright (handles JavaScript-rendered content)
2. Parses HTML with BeautifulSoup to extract contact details
3. Follows "Contact Us" links to find additional information
4. Returns structured, validated contact data in JSON format

### Files Implemented

- **schemas/contact_models.py** - Defines Pydantic models for:

  - `ContactInfo` - Structured contact data (emails, phones, social links, etc.)
  - `ContactExtractionInput` - Input parameters for extraction
  - `ContactExtractionOutput` - Extraction results with metadata
  - `ContactAgentResult` - Final output for BI team integration

- **tools/contact_extractor.py** - Core extraction logic:

  - Web scraping with Playwright
  - HTML parsing with BeautifulSoup
  - Email/phone number regex extraction
  - Social media link detection
  - Contact form identification
  - Address extraction

- **scripts/contact_extraction_cli.py** - Stand-alone CLI to test Step 3 in isolation

- **scripts/contact_agent_full.py** - **Complete end-to-end workflow** (Step 1 → 2 → 3)

### Logic Breakdown

| Stage               | Description                                                              |
| ------------------- | ------------------------------------------------------------------------ |
| 1. Page Loading     | Uses Playwright to load page with JavaScript support, handles timeouts   |
| 2. Email Extraction | Regex patterns to find valid email addresses, filters false positives    |
| 3. Phone Extraction | Detects US/international formats, normalizes to consistent format        |
| 4. Social Media     | Identifies links to Facebook, Instagram, Twitter/X, LinkedIn, etc.       |
| 5. Contact Forms    | Finds HTML forms that appear to be for contact/inquiry                   |
| 6. Address Parsing  | Uses schema.org markup and regex patterns to extract physical addresses  |
| 7. Link Following   | Optionally visits "Contact Us" pages for additional information          |
| 8. Validation       | Validates emails, normalizes phone numbers, calculates confidence scores |

### Contact Information Schema

The `ContactInfo` model aligns with IG team requirements for structured JSON output:

```json
{
  "source_url": "https://example.com",
  "extraction_timestamp": "2025-10-22T10:30:00",
  "emails": ["info@example.com", "support@example.com"],
  "phone_numbers": ["4075551234", "18005551234"],
  "social_links": {
    "facebook": "https://facebook.com/example",
    "instagram": "https://instagram.com/example"
  },
  "contact_forms": ["https://example.com/contact"],
  "address": "123 Main St, Orlando, FL 32816",
  "company_name": "Example Company",
  "confidence_score": 0.9,
  "extraction_method": "multi_page (2 pages)"
}
```

### Example CLI Usage

**Test Step 3 in isolation:**

```bash
python -m scripts.contact_extraction_cli --url "https://www.ucf.edu/about" --company "UCF"
```

**Complete end-to-end workflow (Step 1 → 2 → 3):**

```bash
# Using dummy provider (for testing without API key)
python -m scripts.contact_agent_full --query "find contact info for Joe's Lawncare in Orlando" --provider dummy

# Using SerpAPI for real Google search results
python -m scripts.contact_agent_full --query "UCF Computer Science Department contact" --provider serpapi

# Output as JSON for BI team integration
python -m scripts.contact_agent_full --query "Shah's Halal Orlando" --provider serpapi --json
```

### Design Trade-offs & Findings

| **Option**                  | **Consideration**                                                        | **Decision**                             |
| --------------------------- | ------------------------------------------------------------------------ | ---------------------------------------- |
| **Playwright vs. Requests** | Playwright handles JavaScript-rendered content; slower but more reliable | ✅ Use Playwright for POC                |
| **Contact Page Following**  | Following links increases coverage but adds latency                      | ✅ Optional flag (default: enabled)      |
| **Validation Strictness**   | Strict validation reduces false positives but may miss edge cases        | ✅ Moderate validation with filters      |
| **Confidence Scoring**      | Simple weighted scoring vs. ML model                                     | ✅ Simple scoring for MVP                |
| **Error Handling**          | Graceful degradation vs. strict failure                                  | ✅ Graceful with detailed error messages |

### Integration with Browser Interaction Team

The `ContactAgentResult` model is designed for seamless handoff to the BI team:

```python
ContactAgentResult(
    original_query="find contact for Joe's Lawncare in Orlando",
    normalized_task={...},  # Step 1 output
    domains_searched=5,     # Step 2 metrics
    best_domain="https://joeslawncare.com",
    contact_data=ContactInfo(...),  # Step 3 output
    success=True,
    confidence=0.85,
    evidence={
        "pages_visited": [...],
        "extraction_duration": 12.5,
        "domain_candidates": [...]
    },
    errors=[],
    fallback_triggered=False
)
```

This structured output includes:

- **Evidence trail** for verification (pages visited, domain candidates)
- **Success metrics** (confidence scores, error logs)
- **Fallback status** (whether backup domains were used)
- **Clean contact data** ready for browser automation


**Agent Pipeline Integration:**

```
Overseer (Step 1: Normalize)
  → Execution (Step 2: Domain Finding)
  → Execution (Step 3: Contact Extraction)
  → Verification (Built-in validation)
  → Fallback (Automatic retry with alternate domains)
  → Finish (Structured ContactAgentResult)
```

### Installation & Setup

1. **Install dependencies:**

```bash
pip install -r requirements.txt
playwright install chromium
```

2. **Set up SerpAPI key** (for live search):

```bash
# Create .env file in project root
echo "SERPAPI_KEY=your_key_here" > .env
```

3. **Run tests:**

```bash
# Test individual steps
python -m scripts.task_parser
python -m scripts.domain_finder_cli --company "UCF" --provider dummy
python -m scripts.contact_extraction_cli --url "https://www.ucf.edu" --company "UCF"

# Test complete workflow
python -m scripts.contact_agent_full --query "UCF Computer Science contact" --provider dummy
```

