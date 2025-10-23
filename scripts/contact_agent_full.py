"""
Complete Contact Agent Workflow - End-to-End POC

This script demonstrates the full contact agent pipeline:
  Step 1: Query Normalization (ContactLookupTask)
  Step 2: Domain Finding (DomainFinder)
  Step 3: Contact Extraction (ContactExtractor)

Usage:
  python -m scripts.contact_agent_full --query "find contact info for Joe's Lawncare in Orlando"
  python -m scripts.contact_agent_full --query "UCF Computer Science Department contact" --provider serpapi
"""

import argparse
import json
import sys
from typing import Optional

from schemas.contact_lookup_task import ContactLookupTask
from schemas.domain_finder_models import DomainFinderInput
from schemas.contact_models import ContactExtractionInput, ContactAgentResult
from tools.search_providers import SerpAPIProvider, DummyProvider
from tools.domain_finder import find_domains
from tools.contact_extractor import extract_contact_information


def get_provider(name: str):
    """Get the search provider based on name"""
    if name == "serpapi":
        return SerpAPIProvider()
    if name == "dummy":
        return DummyProvider([
            {"url": "https://joeslawncare.com/", "title": "Joe's Lawncare – Home", "snippet": "Official site"},
            {"url": "https://www.facebook.com/joeslawncare", "title": "Facebook", "snippet": "Business page"},
        ])
    raise SystemExit(f"Unknown provider: {name}. Use serpapi or dummy")


def print_step_header(step_num: int, title: str):
    """Print a formatted step header"""
    print(f"\n{'='*70}")
    print(f"STEP {step_num}: {title}")
    print('='*70)


def run_contact_agent(query: str, provider_name: str = "serpapi", max_domains: int = 5) -> ContactAgentResult:
    """
    Run the complete contact agent workflow.
    
    Returns a ContactAgentResult that aligns with the IG team's
    requirement to provide structured JSON output to the BI team.
    """
    errors = []
    fallback_triggered = False
    
    # ============================================================================
    # STEP 1: NORMALIZE QUERY
    # ============================================================================
    print_step_header(1, "Query Normalization")
    try:
        task = ContactLookupTask.from_raw(query)
        print(f"✓ Original Query: {query}")
        print(f"✓ Normalized Task:")
        print(f"   • Company: {task.company}")
        print(f"   • Location: {task.location_hint or 'N/A'}")
        print(f"   • Target Year: {task.target_year or 'N/A'}")
        print(f"   • Hint URL: {task.hint_url or 'N/A'}")
    except Exception as e:
        error_msg = f"Step 1 failed: {str(e)}"
        errors.append(error_msg)
        print(f"✗ Error: {error_msg}")
        return ContactAgentResult(
            original_query=query,
            normalized_task={},
            success=False,
            errors=errors
        )
    
    # ============================================================================
    # STEP 2: DOMAIN FINDING
    # ============================================================================
    print_step_header(2, "Domain Finding")
    try:
        provider = get_provider(provider_name)
        df_input = DomainFinderInput(
            company=task.company,
            location_hint=task.location_hint,
            k=10,
            provider=provider_name
        )
        
        print(f"🔍 Searching for domains matching: {task.company}")
        if task.location_hint:
            print(f"📍 Location filter: {task.location_hint}")
        
        df_output = find_domains(df_input, provider)
        
        print(f"\n✓ Found {len(df_output.candidates)} domain candidates:")
        for idx, candidate in enumerate(df_output.candidates, 1):
            print(f"\n   {idx}. {candidate.url}")
            print(f"      Score: {candidate.score:.2f}")
            print(f"      Reason: {candidate.reason}")
        
        if not df_output.candidates:
            error_msg = "No domain candidates found"
            errors.append(error_msg)
            print(f"\n✗ {error_msg}")
            return ContactAgentResult(
                original_query=query,
                normalized_task=task.model_dump(),
                success=False,
                errors=errors
            )
        
        # Select the top candidate
        best_candidate = df_output.candidates[0]
        print(f"\n✓ Selected best candidate: {best_candidate.url}")
        
    except Exception as e:
        error_msg = f"Step 2 failed: {str(e)}"
        errors.append(error_msg)
        print(f"✗ Error: {error_msg}")
        return ContactAgentResult(
            original_query=query,
            normalized_task=task.model_dump(),
            domains_searched=0,
            success=False,
            errors=errors
        )
    
    # ============================================================================
    # STEP 3: CONTACT EXTRACTION
    # ============================================================================
    print_step_header(3, "Contact Information Extraction")
    try:
        ce_input = ContactExtractionInput(
            url=best_candidate.url,
            company_name=task.company,
            timeout=30,
            follow_contact_links=True
        )
        
        print(f"🌐 Extracting contact info from: {best_candidate.url}")
        print(f"⏱️  Please wait... (this may take up to 30 seconds)")
        
        ce_output = extract_contact_information(ce_input)
        
        print(f"\n✓ Extraction completed in {ce_output.extraction_duration:.2f}s")
        print(f"✓ Pages visited: {len(ce_output.pages_visited)}")
        
        if not ce_output.success:
            error_msg = f"Contact extraction failed: {ce_output.error_message}"
            errors.append(error_msg)
            print(f"✗ {error_msg}")
            
            # Try fallback to next domain
            if len(df_output.candidates) > 1:
                print("\n⚠️  Triggering fallback to next domain candidate...")
                fallback_triggered = True
                best_candidate = df_output.candidates[1]
                ce_input.url = best_candidate.url
                ce_output = extract_contact_information(ce_input)
                
                if ce_output.success:
                    print(f"✓ Fallback successful using: {best_candidate.url}")
                    errors.append("Primary domain failed, fallback succeeded")
                else:
                    return ContactAgentResult(
                        original_query=query,
                        normalized_task=task.model_dump(),
                        domains_searched=len(df_output.candidates),
                        best_domain=str(best_candidate.url),
                        success=False,
                        errors=errors,
                        fallback_triggered=fallback_triggered
                    )
        
        contact_info = ce_output.contact_info
        
        if not contact_info:
            error_msg = "No contact information extracted"
            errors.append(error_msg)
            print(f"✗ {error_msg}")
        else:
            print(f"\n📊 Extraction Quality:")
            print(f"   • Confidence Score: {contact_info.confidence_score:.2f}")
            print(f"   • Emails Found: {len(contact_info.emails)}")
            print(f"   • Phone Numbers Found: {len(contact_info.phone_numbers)}")
            print(f"   • Social Links Found: {len(contact_info.social_links)}")
            print(f"   • Contact Forms Found: {len(contact_info.contact_forms)}")
            print(f"   • Address Found: {'Yes' if contact_info.address else 'No'}")
        
    except Exception as e:
        error_msg = f"Step 3 failed: {str(e)}"
        errors.append(error_msg)
        print(f"✗ Error: {error_msg}")
        return ContactAgentResult(
            original_query=query,
            normalized_task=task.model_dump(),
            domains_searched=len(df_output.candidates),
            best_domain=str(best_candidate.url),
            success=False,
            errors=errors,
            fallback_triggered=fallback_triggered
        )
    
    # ============================================================================
    # FINAL RESULT
    # ============================================================================
    result = ContactAgentResult(
        original_query=query,
        normalized_task=task.model_dump(),
        domains_searched=len(df_output.candidates),
        best_domain=str(best_candidate.url),
        contact_data=contact_info,
        success=ce_output.success and contact_info is not None,
        confidence=contact_info.confidence_score if contact_info else 0.0,
        evidence={
            "pages_visited": ce_output.pages_visited,
            "extraction_duration": ce_output.extraction_duration,
            "domain_candidates": [
                {"url": str(c.url), "score": c.score, "reason": c.reason}
                for c in df_output.candidates
            ]
        },
        errors=errors,
        fallback_triggered=fallback_triggered
    )
    
    return result


def print_final_summary(result: ContactAgentResult):
    """Print a formatted summary of the final result"""
    print_step_header(4, "Final Result Summary")
    
    print(f"\n{'Status:':<20} {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"{'Overall Confidence:':<20} {result.confidence:.2%}")
    print(f"{'Domains Searched:':<20} {result.domains_searched}")
    print(f"{'Best Domain:':<20} {result.best_domain or 'N/A'}")
    print(f"{'Fallback Used:':<20} {'Yes' if result.fallback_triggered else 'No'}")
    
    if result.errors:
        print(f"\n⚠️  Errors encountered ({len(result.errors)}):")
        for error in result.errors:
            print(f"   • {error}")
    
    if result.contact_data:
        contact = result.contact_data
        print(f"\n📋 CONTACT INFORMATION:")
        print(f"{'─'*70}")
        
        if contact.company_name:
            print(f"\n🏢 Company: {contact.company_name}")
        
        if contact.emails:
            print(f"\n📧 Email{'s' if len(contact.emails) > 1 else ''}:")
            for email in contact.emails:
                print(f"   • {email}")
        
        if contact.phone_numbers:
            print(f"\n📞 Phone{'s' if len(contact.phone_numbers) > 1 else ''}:")
            for phone in contact.phone_numbers:
                print(f"   • {phone}")
        
        if contact.social_links:
            print(f"\n🌐 Social Media:")
            for platform, url in contact.social_links.items():
                print(f"   • {platform.title()}: {url}")
        
        if contact.contact_forms:
            print(f"\n📝 Contact Forms:")
            for form in contact.contact_forms:
                print(f"   • {form}")
        
        if contact.address:
            print(f"\n📍 Address:")
            print(f"   {contact.address}")
    
    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Complete Contact Agent - Find contact information for any company",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with dummy provider (for testing)
  python -m scripts.contact_agent_full --query "find contact info for Joe's Lawncare in Orlando" --provider dummy
  
  # Use SerpAPI for real Google search results
  python -m scripts.contact_agent_full --query "UCF Computer Science Department contact" --provider serpapi
  
  # Output as JSON for BI team integration
  python -m scripts.contact_agent_full --query "Shah's Halal Orlando" --json
  
Note: SerpAPI requires SERPAPI_KEY environment variable to be set.
      Set it in a .env file or export SERPAPI_KEY=your_key_here
        """
    )
    
    parser.add_argument(
        '--query',
        required=True,
        help='Natural language query for contact information'
    )
    
    parser.add_argument(
        '--provider',
        default='dummy',
        choices=['serpapi', 'dummy'],
        help='Search provider to use (default: dummy)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output result as JSON (for BI team integration)'
    )
    
    parser.add_argument(
        '--output',
        help='Save JSON output to file'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("CONTACT AGENT - PROOF OF CONCEPT")
    print("Information Gathering Team - L07")
    print("="*70)
    
    # Run the complete workflow
    result = run_contact_agent(args.query, args.provider)
    
    # Display results
    if args.json:
        json_output = json.dumps(result.model_dump(), indent=2, default=str)
        print("\n" + json_output)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(json_output)
            print(f"\n✓ Output saved to: {args.output}")
    else:
        print_final_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

