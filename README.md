# DOM Q&A Processor Module

A question-answering system that extracts answers from HTML DOM content using BM25 retrieval and transformer-based QA models.

## Features

- **DOM Parsing**: Extracts visible text chunks from HTML with heading context, XPath tracking, and intelligent chunking
- **BM25 Retrieval**: Fast keyword-based retrieval to find relevant content chunks
- **Question Answering**: Uses Hugging Face transformers (DistilBERT) for extractive QA
- **Confidence Scoring**: Blends retriever and QA scores with span sanity checks and abstain logic
- **REST API**: FastAPI endpoint for easy integration
- **Configurable**: YAML-based configuration for all parameters

## Installation

### Prerequisites

- Python 3.10+
- pip

### Setup

1. **Clone the repository** (or navigate to the directory):
   ```bash
   cd "Data Processing Module"
   ```

2. **Create and activate virtual environment**:
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Download Playwright browsers** (if needed for browser automation):
   ```bash
   playwright install
   ```

## Quick Start

### Running the API Server

Start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### API Usage

#### Health Check

```bash
curl http://localhost:8000/
```

#### Answer a Question

```bash
curl -X POST "http://localhost:8000/answer" \
  -H "Content-Type: application/json" \
  -d '{
    "dom": "<html><body><h1>Refund Policy</h1><p>Refunds are available within 30 days of purchase.</p></body></html>",
    "prompt": "What is the refund deadline?"
  }'
```

**Response:**
```json
{
  "answer": "30 days",
  "confidence": 0.85,
  "source": {
    "node_id": null,
    "xpath": "/html[1]/body[1]/p[1]",
    "text_snippet": "Refunds are available within 30 days of purchase."
  }
}
```

### Using the Pipeline Directly

```python
from core.pipeline import answer

# Parse HTML and answer question
html = """
<html>
  <body>
    <h1>Shipping Policy</h1>
    <p>Free shipping on orders over $50. Standard shipping takes 5-7 business days.</p>
  </body>
</html>
"""

response = answer(html, "What is the shipping time?")
print(f"Answer: {response.answer}")
print(f"Confidence: {response.confidence}")
print(f"Source: {response.source.text_snippet}")
```

## Configuration

Edit `config/config.yaml` to customize behavior:

```yaml
retrieval:
  method: "bm25"          # Retrieval method
  top_k: 3                # Number of top chunks to retrieve

parser:
  max_chunk_len: 1200     # Maximum characters per chunk
  include_tables: true    # Include table cells in parsing

qa:
  model_name: "distilbert-base-cased-distilled-squad"  # Hugging Face QA model
  max_answer_len: 64      # Maximum answer length

scoring:
  weight_retriever: 0.35  # Weight for retriever score
  weight_qa: 0.65         # Weight for QA score
  min_answer_chars: 2     # Minimum answer length
  max_answer_chars: 200   # Maximum answer length
  span_penalty: 0.15      # Penalty for invalid span lengths
  abstain_threshold: 0.5   # Confidence threshold for abstaining
  retriever_abstain_threshold: 0.2  # Retriever score threshold
  raw_score_threshold: 0.8  # Raw BM25 score threshold

api:
  max_dom_size_mb: 10     # Maximum DOM size in MB
```

## Project Structure

```
.
├── app/
│   └── main.py              # FastAPI application
├── core/
│   ├── __init__.py
│   ├── config.py            # Configuration loader
│   ├── dom_parser.py        # DOM parsing and chunking
│   ├── models.py            # Pydantic data models
│   ├── pipeline.py          # Main orchestration pipeline
│   ├── qa.py                # Question-answering with transformers
│   ├── retrieval.py         # BM25 retrieval
│   └── scoring.py           # Confidence scoring and abstain logic
├── config/
│   └── config.yaml          # Configuration file
├── data/
│   └── samples/             # Sample HTML files
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Core Components

### DOM Parser (`core/dom_parser.py`)
- Extracts text from block-level elements (p, li, section, article, div, td, th)
- Finds nearest headings for context
- Generates XPath for provenance
- Splits long text on sentence boundaries
- Respects `max_chunk_len` configuration

### Retrieval (`core/retrieval.py`)
- BM25-based keyword retrieval
- Tokenizes and normalizes scores to [0, 1]
- Returns top-K most relevant chunks
- Detects when queries don't match content

### Question Answering (`core/qa.py`)
- Uses Hugging Face transformers pipeline
- Singleton pattern to avoid repeated model loading
- Extracts answer spans from context
- Evaluates multiple chunks and selects best

### Scoring (`core/scoring.py`)
- Blends retriever and QA scores with configurable weights
- Applies span length sanity checks
- Multiple abstain strategies:
  - Low confidence threshold
  - Low retriever score
  - Low raw BM25 score
  - Low score spread (no clear winner)

### Pipeline (`core/pipeline.py`)
- Orchestrates: parse → retrieve → QA → score → response
- Handles edge cases (empty DOM, no matches, etc.)
- Extracts source snippets with context window
- Returns structured `AnswerResponse`

## API Endpoints

### `GET /`
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "service": "DOM Q&A API"
}
```

### `POST /answer`
Answer a question about DOM content.

**Request Body:**
```json
{
  "dom": "<html>...</html>",
  "prompt": "Your question here",
  "options": {}  // Optional
}
```

**Response:**
```json
{
  "answer": "Extracted answer text",
  "confidence": 0.85,
  "source": {
    "node_id": "element-id",
    "xpath": "/html[1]/body[1]/p[1]",
    "text_snippet": "Context around the answer..."
  }
}
```

**Error Responses:**
- `400`: Invalid request (empty DOM or prompt)
- `413`: DOM content too large
- `500`: Processing error

## Dependencies

- **fastapi**: Web framework for API
- **uvicorn**: ASGI server
- **beautifulsoup4**: HTML parsing
- **lxml**: Fast HTML parser
- **rank-bm25**: BM25 retrieval algorithm
- **transformers**: Hugging Face transformers for QA
- **torch**: PyTorch (required by transformers)
- **numpy**: Numerical operations
- **pydantic**: Data validation
- **pyyaml**: YAML configuration parsing

## Notes

- The QA model (`distilbert-base-cased-distilled-squad`) will be downloaded automatically on first use (~250MB)
- DOM size is limited to 10MB by default (configurable)
- The system will abstain from answering if confidence is too low or content doesn't match the question
- All scores are normalized to [0, 1] range

## License

MIT

