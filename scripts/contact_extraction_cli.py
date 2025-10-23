"""
Contact Extraction CLI - Test Step 3 in Isolation

Usage:
  python -m scripts.contact_extraction_cli --url "https://example.com" --company "Example Corp"
"""

import argparse
import json
from pydantic import HttpUrl
from schemas.contact_models import ContactExtractionInput
from tools.contact_extractor import extract_contact_information


def format_contact_info(output):
    """Pretty print contact extraction results"""
    print("\n" + "="*70)
    print("CONTACT EXTRACTION RESULTS")
    print("="*70)
    
    print(f"\n✓ Success: {output.success}")
    print(f"✓ Duration: {output.extraction_duration:.2f}s")
    print(f"✓ Pages Visited: {len(output.pages_visited)}")
    for page in output.pages_visited:
        print(f"   - {page}")
    
    if output.error_message:
        print(f"\n✗ Error: {output.error_message}")
        return
    
    if not output.contact_info:
        print("\n⚠ No contact information extracted")
        return
    
    contact = output.contact_info
    
    print(f"\n📋 Company: {contact.company_name or 'N/A'}")
    print(f"📊 Confidence Score: {contact.confidence_score:.2f}")
    print(f"🔧 Extraction Method: {contact.extraction_method}")
    
    if contact.emails:
        print(f"\n📧 Emails ({len(contact.emails)}):")
        for email in contact.emails:
            print(f"   • {email}")
    else:
        print("\n📧 Emails: None found")
    
    if contact.phone_numbers:
        print(f"\n📞 Phone Numbers ({len(contact.phone_numbers)}):")
        for phone in contact.phone_numbers:
            print(f"   • {phone}")
    else:
        print("\n📞 Phone Numbers: None found")
    
    if contact.social_links:
        print(f"\n🌐 Social Media ({len(contact.social_links)}):")
        for platform, url in contact.social_links.items():
            print(f"   • {platform.title()}: {url}")
    else:
        print("\n🌐 Social Media: None found")
    
    if contact.contact_forms:
        print(f"\n📝 Contact Forms ({len(contact.contact_forms)}):")
        for form_url in contact.contact_forms:
            print(f"   • {form_url}")
    else:
        print("\n📝 Contact Forms: None found")
    
    if contact.address:
        print(f"\n📍 Address:\n   {contact.address}")
    else:
        print("\n📍 Address: None found")
    
    print("\n" + "="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Extract contact information from a website",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from a specific URL
  python -m scripts.contact_extraction_cli --url "https://www.ucf.edu/about" --company "UCF"
  
  # Extract without following contact links
  python -m scripts.contact_extraction_cli --url "https://example.com" --no-follow
  
  # Output as JSON
  python -m scripts.contact_extraction_cli --url "https://example.com" --json
        """
    )
    
    parser.add_argument(
        '--url',
        required=True,
        help='URL to extract contact information from'
    )
    
    parser.add_argument(
        '--company',
        default=None,
        help='Expected company name (optional, helps with validation)'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='Timeout in seconds for page load (default: 30)'
    )
    
    parser.add_argument(
        '--no-follow',
        action='store_true',
        help='Do not follow contact links (only scrape main page)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    # Create input
    input_data = ContactExtractionInput(
        url=HttpUrl(args.url),
        company_name=args.company,
        timeout=args.timeout,
        follow_contact_links=not args.no_follow
    )
    
    print(f"\n🔍 Extracting contact information from: {args.url}")
    if args.company:
        print(f"🏢 Expected company: {args.company}")
    print(f"⏱️  Timeout: {args.timeout}s")
    print(f"🔗 Follow contact links: {not args.no_follow}")
    
    # Extract contact information
    output = extract_contact_information(input_data)
    
    # Display results
    if args.json:
        print("\n" + json.dumps(output.model_dump(), indent=2, default=str))
    else:
        format_contact_info(output)


if __name__ == "__main__":
    main()

