"""
Evidence capture utilities for screenshots and DOM snippets
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from playwright.async_api import Page, Locator

RUN_STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

class EvidenceCapture:
    """Handles evidence capture for actions"""
    
    def __init__(self, output_dir: Optional[str] = None):
        # 1) allow env var override
        env_dir = os.getenv("IG_EVIDENCE_DIR")
        if output_dir is None:
            if env_dir:
                base = Path(env_dir)
            else:
                # 2) default to repo-local artifacts/evidence
                # try to find repo root by walking up to .git or pyproject.toml
                here = Path(__file__).resolve()
                root = next(
                    (p for p in [*here.parents] if (p / ".git").exists() or (p / "pyproject.toml").exists()),
                    Path.cwd()
                )
                base = root / "artifacts" / "evidence"
            # 3) per-run subfolder to keep files grouped
            self.output_dir = base / RUN_STAMP
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def capture_screenshot(
        self,
        page: Page,
        trace_id: str,
        element: Optional[Locator] = None,
        clip_to_element: bool = True
    ) -> Optional[str]:
        """
        Capture a screenshot
        
        Args:
            page: Playwright page
            trace_id: Trace ID for naming
            element: Optional element to clip to
            clip_to_element: Whether to clip to element bounds
            
        Returns:
            Path to saved screenshot or None
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{trace_id}_{timestamp}.png"
        filepath = self.output_dir / filename
        
        try:
            if element and clip_to_element:
                # Try to clip to element's bounding box
                try:
                    await element.screenshot(path=str(filepath))
                except:
                    # Fall back to full page if element screenshot fails
                    await page.screenshot(path=str(filepath))
            else:
                # Full page screenshot
                await page.screenshot(path=str(filepath))
            
            return str(filepath)
        except Exception as e:
            print(f"Failed to capture screenshot: {e}")
            return None
    
    async def capture_dom_snippet(
        self,
        page: Page,
        trace_id: str,
        element: Optional[Locator] = None,
        max_chars: int = 4000
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Capture a DOM snippet around the target element
        
        Args:
            page: Playwright page
            trace_id: Trace ID for naming
            element: Optional element to center snippet around
            max_chars: Maximum characters to capture
            
        Returns:
            Tuple of (filepath, context_selector)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{trace_id}_{timestamp}_dom.html"
        filepath = self.output_dir / filename
        
        try:
            if element:
                # Get outer HTML of element and its context
                try:
                    # Try to get the element's outer HTML
                    element_html = await element.evaluate('''
                        (el) => {
                            // Get element and some parent context
                            let html = el.outerHTML;
                            let parent = el.parentElement;
                            if (parent) {
                                // Include parent tag opening
                                let parentTag = parent.tagName.toLowerCase();
                                let parentAttrs = Array.from(parent.attributes)
                                    .map(a => `${a.name}="${a.value}"`)
                                    .join(' ');
                                html = `<${parentTag} ${parentAttrs}>...${html}...</${parentTag}>`;
                            }
                            return html;
                        }
                    ''')
                    
                    # Truncate if needed
                    if len(element_html) > max_chars:
                        element_html = element_html[:max_chars] + "..."
                    
                    # Save snippet
                    filepath.write_text(element_html, encoding='utf-8')
                    
                    # Try to get a selector for the element
                    context_selector = await element.evaluate('''
                        (el) => {
                            if (el.id) return '#' + el.id;
                            if (el.className) return '.' + el.className.split(' ').join('.');
                            return el.tagName.toLowerCase();
                        }
                    ''')
                    
                    return str(filepath), context_selector
                    
                except:
                    # Fall back to page content
                    pass
            
            # Fall back to getting part of page content
            content = await page.content()
            if len(content) > max_chars:
                # Take from the middle of the page
                start = max(0, len(content) // 2 - max_chars // 2)
                content = "..." + content[start:start + max_chars] + "..."
            
            filepath.write_text(content, encoding='utf-8')
            return str(filepath), None
            
        except Exception as e:
            print(f"Failed to capture DOM snippet: {e}")
            return None, None
    
    async def get_visible_text(self, element: Optional[Locator]) -> Optional[str]:
        """
        Get visible text from an element
        
        Args:
            element: Element to get text from
            
        Returns:
            Visible text or None
        """
        if not element:
            return None
        
        try:
            text = await element.inner_text()
            return text.strip() if text else None
        except:
            return None


evidence_capture = EvidenceCapture()