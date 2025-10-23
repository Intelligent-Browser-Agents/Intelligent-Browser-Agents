from pydantic import BaseModel, HttpUrl, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime

class ContactInfo(BaseModel):
    """
    Structured contact information extracted from a website.
    
    This schema represents the output of the contact extraction process,
    aligning with the IG team's requirement to produce clean, structured
    JSON outputs for the Browser Interaction team to consume.
    """
    # Source information
    source_url: HttpUrl = Field(..., description="URL where this contact info was extracted from")
    extraction_timestamp: datetime = Field(default_factory=datetime.now, description="When this data was extracted")
    
    # Contact details
    emails: List[str] = Field(default_factory=list, description="Email addresses found")
    phone_numbers: List[str] = Field(default_factory=list, description="Phone numbers found (normalized format)")
    
    # Social media links
    social_links: Dict[str, str] = Field(
        default_factory=dict, 
        description="Social media platform -> URL mapping (facebook, instagram, twitter, linkedin, etc.)"
    )
    
    # Additional contact methods
    contact_forms: List[str] = Field(default_factory=list, description="URLs to contact forms")
    address: Optional[str] = Field(None, description="Physical address if found")
    
    # Metadata
    company_name: Optional[str] = Field(None, description="Company name as found on the website")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in extraction quality (0-1)")
    extraction_method: Optional[str] = Field(None, description="Method used for extraction (e.g., 'contact_page', 'footer', 'about_page')")
    
    @field_validator('emails')
    @classmethod
    def validate_emails(cls, v):
        """Basic email validation"""
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return [email for email in v if re.match(email_pattern, email)]
    
    @field_validator('phone_numbers')
    @classmethod
    def normalize_phone_numbers(cls, v):
        """Normalize phone numbers to a consistent format"""
        import re
        normalized = []
        for phone in v:
            # Remove common separators and keep only digits and +
            cleaned = re.sub(r'[^\d+]', '', phone)
            if len(cleaned) >= 10:  # Minimum valid phone number length
                normalized.append(cleaned)
        return normalized


class ContactExtractionInput(BaseModel):
    """Input for contact extraction process"""
    url: HttpUrl = Field(..., description="URL to extract contact information from")
    company_name: Optional[str] = Field(None, description="Expected company name for validation")
    timeout: int = Field(30, description="Timeout in seconds for page load")
    extract_social: bool = Field(True, description="Whether to extract social media links")
    follow_contact_links: bool = Field(True, description="Whether to follow 'contact us' links")


class ContactExtractionOutput(BaseModel):
    """Output from contact extraction process"""
    input_data: ContactExtractionInput
    contact_info: Optional[ContactInfo] = Field(None, description="Extracted contact information")
    success: bool = Field(False, description="Whether extraction succeeded")
    error_message: Optional[str] = Field(None, description="Error message if extraction failed")
    pages_visited: List[str] = Field(default_factory=list, description="List of pages visited during extraction")
    extraction_duration: float = Field(0.0, description="Time taken for extraction in seconds")


class ContactAgentResult(BaseModel):
    """
    Final output from the complete contact agent workflow.
    This is what gets passed to the Browser Interaction team.
    """
    # Original query
    original_query: str
    normalized_task: Dict = Field(..., description="Normalized ContactLookupTask as dict")
    
    # Domain finding results
    domains_searched: int = Field(0, description="Number of domain candidates evaluated")
    best_domain: Optional[str] = Field(None, description="Top-ranked domain used for extraction")
    
    # Contact information
    contact_data: Optional[ContactInfo] = Field(None, description="Extracted contact information")
    
    # Success metrics
    success: bool = Field(False, description="Overall success of the workflow")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Overall confidence in results")
    
    # Evidence (for Browser Interaction team verification)
    evidence: Dict = Field(
        default_factory=dict,
        description="Evidence trail (screenshots, HTML snapshots, etc.)"
    )
    
    # Error handling
    errors: List[str] = Field(default_factory=list, description="List of errors encountered")
    fallback_triggered: bool = Field(False, description="Whether fallback logic was triggered")

