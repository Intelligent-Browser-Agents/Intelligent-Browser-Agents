from pydantic import BaseModel, HttpUrl, Field
from typing import Optional

class ContactLookupTask(BaseModel):
  company: str = Field(..., description="Company or organization name to search for")
  target_year: Optional[int] = Field(None, description="Preferred data year if specified")
  hint_url: Optional[HttpUrl] = Field(None, description="Optional user-provided site URL")
  location_hint: Optional[str] = Field(None, description="City, state, or region hint")
  
  @classmethod
  def from_raw(cls, raw_query: str):
      """Lightweight parser that extracts structured info from natural language."""
      import re

      # Normalize spacing and lowercase for easier matching
      query = re.sub(r"\s+", " ", raw_query).strip()

      # Detect 4-digit year
      year_match = re.search(r"\b(19|20)\d{2}\b", query)
      year = int(year_match.group(0)) if year_match else None

      # Detect location
      loc_match = re.search(r"\b(?:in|near)\s+([A-Za-z\s,]+)", query)
      location = loc_match.group(1).strip() if loc_match else None

      # Remove the parts we already extracted
      cleaned = query
      if year:
          cleaned = re.sub(str(year), "", cleaned)
      if location:
          cleaned = re.sub(rf"\b(?:in|near)\s+{re.escape(location)}", "", cleaned, flags=re.IGNORECASE)

      # Remove generic keywords and connectors
      cleaned = re.sub(r"\b(find|get|show|fetch|contact(?:\s+info|(?:\s+details)?)|for|details)\b", "", cleaned, flags=re.IGNORECASE)
      cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")

      return cls(company=cleaned, target_year=year, location_hint=location)
