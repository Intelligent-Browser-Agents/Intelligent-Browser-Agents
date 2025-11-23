from pydantic import BaseModel, field_validator, Field


class AnswerRequest(BaseModel):
    dom: str = Field(..., min_length=1, description="HTML DOM content (non-empty)")
    prompt: str = Field(..., min_length=1, description="Question or prompt (non-empty)")
    options: dict | None = None
    
    @field_validator('dom')
    @classmethod
    def validate_dom_not_empty(cls, v: str) -> str:
        """Validate that DOM is not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError("DOM content cannot be empty")
        return v
    
    @field_validator('prompt')
    @classmethod
    def validate_prompt_not_empty(cls, v: str) -> str:
        """Validate that prompt is not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v


class SourceInfo(BaseModel):
    node_id: str | None = None
    xpath: str | None = None
    text_snippet: str


class AnswerResponse(BaseModel):
    answer: str
    confidence: float  # 0..1
    source: SourceInfo

