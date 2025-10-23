"""
Contact Extraction Tool - Step 3 of Contact Agent POC

This module implements web scraping logic to extract contact information
from candidate domains identified in Step 2.

Uses Playwright for browser automation and BeautifulSoup for HTML parsing.
"""

import re
import time
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from pydantic import HttpUrl

try:
    from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright not installed. Install with: pip install playwright && playwright install")

from bs4 import BeautifulSoup
from schemas.contact_models import ContactInfo, ContactExtractionInput, ContactExtractionOutput

# Common social media platforms and their domain patterns
SOCIAL_PLATFORMS = {
    'facebook': r'facebook\.com|fb\.com|fb\.me',
    'instagram': r'instagram\.com|instagr\.am',
    'twitter': r'twitter\.com|x\.com',
    'linkedin': r'linkedin\.com',
    'youtube': r'youtube\.com|youtu\.be',
    'tiktok': r'tiktok\.com',
    'pinterest': r'pinterest\.com',
}

# Common contact-related keywords for finding contact pages
CONTACT_KEYWORDS = [
    'contact', 'contact-us', 'contactus', 'get-in-touch',
    'about', 'about-us', 'aboutus', 'reach-us', 'connect'
]


def extract_emails(text: str) -> List[str]:
    """
    Extract email addresses from text using regex.
    Filters out common false positives and image file extensions.
    """
    # Standard email pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    
    # Filter out common false positives
    filtered = []
    for email in emails:
        email_lower = email.lower()
        # Skip if it's an image or asset file
        if any(ext in email_lower for ext in ['.png', '.jpg', '.gif', '.svg', '.css', '.js']):
            continue
        # Skip common placeholder emails
        if any(placeholder in email_lower for placeholder in ['example.com', 'domain.com', 'test.com']):
            continue
        filtered.append(email)
    
    return list(set(filtered))  # Remove duplicates


def extract_phone_numbers(text: str) -> List[str]:
    """
    Extract phone numbers from text using multiple patterns.
    Handles US and international formats.
    """
    patterns = [
        # US formats
        r'\+?1?[-.\s]?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
        # International format
        r'\+[0-9]{1,3}[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,9}',
        # Simple format
        r'\b[0-9]{3}[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b',
    ]
    
    phones = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            if isinstance(matches[0], tuple):
                # Pattern with groups - reconstruct
                phones.extend([f"{m[0]}{m[1]}{m[2]}" for m in matches])
            else:
                phones.extend(matches)
    
    return list(set(phones))


def extract_social_links(soup: BeautifulSoup, base_url: str) -> dict:
    """
    Extract social media links from HTML.
    Returns a dictionary mapping platform names to URLs.
    """
    social_links = {}
    
    # Find all links
    for link in soup.find_all('a', href=True):
        href = link['href']
        absolute_url = urljoin(base_url, href)
        
        # Check against each social platform
        for platform, pattern in SOCIAL_PLATFORMS.items():
            if re.search(pattern, absolute_url, re.IGNORECASE):
                if platform not in social_links:  # Keep first occurrence
                    social_links[platform] = absolute_url
    
    return social_links


def extract_address(soup: BeautifulSoup) -> Optional[str]:
    """
    Attempt to extract physical address from HTML.
    Uses common patterns and schema.org markup.
    """
    # Try schema.org markup first
    address_elem = soup.find(attrs={'itemprop': 'address'})
    if address_elem:
        return address_elem.get_text(strip=True)
    
    # Try common address patterns in text
    text = soup.get_text()
    # Look for US address pattern (number + street + city, state zip)
    address_pattern = r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)[,\s]+[\w\s]+,\s+[A-Z]{2}\s+\d{5}'
    match = re.search(address_pattern, text)
    if match:
        return match.group(0)
    
    return None


def find_contact_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """
    Find links to potential contact pages.
    """
    contact_links = []
    
    for link in soup.find_all('a', href=True):
        href = link['href'].lower()
        text = link.get_text().lower()
        
        # Check if link text or href contains contact keywords
        if any(keyword in href or keyword in text for keyword in CONTACT_KEYWORDS):
            absolute_url = urljoin(base_url, link['href'])
            # Avoid duplicates and external links
            if urlparse(absolute_url).netloc == urlparse(base_url).netloc:
                contact_links.append(absolute_url)
    
    return list(set(contact_links))[:3]  # Limit to top 3 contact pages


def find_contact_forms(soup: BeautifulSoup, current_url: str) -> List[str]:
    """
    Find contact forms on the page.
    Returns URLs or identifiers for contact forms.
    """
    forms = []
    
    for form in soup.find_all('form'):
        # Check if form looks like a contact form
        action = form.get('action', '')
        form_id = form.get('id', '').lower()
        form_class = ' '.join(form.get('class', [])).lower()
        
        if any(keyword in f"{form_id} {form_class} {action}".lower() 
               for keyword in ['contact', 'message', 'inquiry', 'email']):
            form_url = urljoin(current_url, action) if action else current_url
            forms.append(form_url)
    
    return list(set(forms))


def scrape_page_with_playwright(url: str, timeout: int = 30) -> Tuple[Optional[str], Optional[str]]:
    """
    Use Playwright to load a page and get its HTML content.
    Returns (html_content, error_message)
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None, "Playwright not available"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Navigate to URL
            page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')
            
            # Wait a bit for dynamic content
            page.wait_for_timeout(2000)
            
            # Get HTML content
            html = page.content()
            
            browser.close()
            return html, None
            
    except PlaywrightTimeout:
        return None, f"Timeout loading page: {url}"
    except Exception as e:
        return None, f"Error loading page: {str(e)}"


def extract_contact_info_from_html(html: str, url: str, company_name: Optional[str] = None) -> ContactInfo:
    """
    Parse HTML and extract all contact information.
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Get all text content
    text_content = soup.get_text()
    
    # Extract contact details
    emails = extract_emails(text_content)
    phones = extract_phone_numbers(text_content)
    social_links = extract_social_links(soup, url)
    address = extract_address(soup)
    contact_forms = find_contact_forms(soup, url)
    
    # Try to extract company name from page if not provided
    if not company_name:
        title_tag = soup.find('title')
        if title_tag:
            company_name = title_tag.get_text(strip=True)
    
    # Calculate confidence score based on what we found
    confidence = 0.0
    if emails:
        confidence += 0.4
    if phones:
        confidence += 0.3
    if social_links:
        confidence += 0.2
    if address:
        confidence += 0.1
    
    return ContactInfo(
        source_url=HttpUrl(url),
        emails=emails,
        phone_numbers=phones,
        social_links=social_links,
        contact_forms=contact_forms,
        address=address,
        company_name=company_name,
        confidence_score=min(confidence, 1.0),
        extraction_method='main_page'
    )


def extract_contact_information(input_data: ContactExtractionInput) -> ContactExtractionOutput:
    """
    Main function to extract contact information from a URL.
    Follows contact links if requested and aggregates results.
    """
    start_time = time.time()
    pages_visited = []
    all_emails: Set[str] = set()
    all_phones: Set[str] = set()
    all_social: dict = {}
    all_forms: Set[str] = set()
    best_address = None
    
    try:
        # Scrape main page
        url_str = str(input_data.url)
        html, error = scrape_page_with_playwright(url_str, timeout=input_data.timeout)
        
        if error:
            return ContactExtractionOutput(
                input_data=input_data,
                success=False,
                error_message=error,
                extraction_duration=time.time() - start_time
            )
        
        pages_visited.append(url_str)
        
        # Extract from main page
        soup = BeautifulSoup(html, 'html.parser')
        main_contact_info = extract_contact_info_from_html(html, url_str, input_data.company_name)
        
        all_emails.update(main_contact_info.emails)
        all_phones.update(main_contact_info.phone_numbers)
        all_social.update(main_contact_info.social_links)
        all_forms.update(main_contact_info.contact_forms)
        if main_contact_info.address:
            best_address = main_contact_info.address
        
        # Follow contact links if requested
        if input_data.follow_contact_links:
            contact_links = find_contact_links(soup, url_str)
            
            for contact_url in contact_links[:2]:  # Limit to 2 additional pages
                if contact_url in pages_visited:
                    continue
                    
                html, error = scrape_page_with_playwright(contact_url, timeout=input_data.timeout)
                if not error and html:
                    pages_visited.append(contact_url)
                    contact_page_info = extract_contact_info_from_html(html, contact_url, input_data.company_name)
                    
                    all_emails.update(contact_page_info.emails)
                    all_phones.update(contact_page_info.phone_numbers)
                    all_social.update(contact_page_info.social_links)
                    all_forms.update(contact_page_info.contact_forms)
                    if not best_address and contact_page_info.address:
                        best_address = contact_page_info.address
        
        # Create final contact info
        final_contact_info = ContactInfo(
            source_url=input_data.url,
            emails=list(all_emails),
            phone_numbers=list(all_phones),
            social_links=all_social,
            contact_forms=list(all_forms),
            address=best_address,
            company_name=input_data.company_name or main_contact_info.company_name,
            confidence_score=main_contact_info.confidence_score,
            extraction_method=f"multi_page ({len(pages_visited)} pages)"
        )
        
        return ContactExtractionOutput(
            input_data=input_data,
            contact_info=final_contact_info,
            success=True,
            pages_visited=pages_visited,
            extraction_duration=time.time() - start_time
        )
        
    except Exception as e:
        return ContactExtractionOutput(
            input_data=input_data,
            success=False,
            error_message=f"Unexpected error: {str(e)}",
            pages_visited=pages_visited,
            extraction_duration=time.time() - start_time
        )

