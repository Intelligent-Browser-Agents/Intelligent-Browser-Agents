from dataclasses import dataclass
from bs4 import BeautifulSoup, Tag
from typing import List
import re

from core.config import load_config

@dataclass
class Chunk:
    id: str
    text: str
    heading: str | None = None
    node_id: str | None = None
    xpath: str | None = None


def _find_nearest_heading(element: Tag) -> str | None:
    """
    Find the nearest heading (h1-h6) by traversing up the DOM tree.
    Checks: previous siblings, parent headings, and ancestors with heading children.
    
    Args:
        element: BeautifulSoup Tag element
        
    Returns:
        Heading text if found, None otherwise
    """
    def is_heading(tag):
        """Check if tag is a heading (h1-h6)."""
        if not tag or not isinstance(tag, Tag) or not tag.name:
            return False
        if tag.name.startswith('h') and len(tag.name) == 2:
            heading_num = tag.name[1]
            return heading_num.isdigit() and '1' <= heading_num <= '6'
        return False
    
    def get_heading_text(tag):
        """Extract heading text from a heading tag."""
        if not is_heading(tag):
            return None
        heading_text = tag.get_text(separator=' ', strip=True)
        return ' '.join(heading_text.split()) if heading_text else None
    
    # Check previous siblings (including in parent's children)
    current = element
    while current and current.name != '[document]':
        # Check previous siblings
        prev = current.previous_sibling
        while prev:
            if isinstance(prev, Tag):
                heading_text = get_heading_text(prev)
                if heading_text:
                    return heading_text
            prev = prev.previous_sibling
        
        # Check if parent is a heading
        if current.parent and isinstance(current.parent, Tag):
            heading_text = get_heading_text(current.parent)
            if heading_text:
                return heading_text
            
            # Check parent's children for headings before current element
            if hasattr(current.parent, 'children'):
                for child in current.parent.children:
                    if child is current:
                        break
                    if isinstance(child, Tag):
                        heading_text = get_heading_text(child)
                        if heading_text:
                            return heading_text
        
        current = current.parent
    
    return None


def _extract_node_id(element: Tag) -> str | None:
    """
    Extract node identifier from element attributes.
    Priority: id > aria-label > first data-* attribute
    
    Args:
        element: BeautifulSoup Tag element
        
    Returns:
        Node identifier if found, None otherwise
    """
    # Check id first
    if element.get('id'):
        return element.get('id')
    
    # Check aria-label
    if element.get('aria-label'):
        return element.get('aria-label')
    
    # Check first data-* attribute
    for attr_name, attr_value in element.attrs.items():
        if attr_name.startswith('data-'):
            return attr_value if isinstance(attr_value, str) else str(attr_value)
    
    return None


def _split_text_on_sentences(text: str, max_len: int) -> List[str]:
    """
    Split text on sentence boundaries if it exceeds max_len.
    Uses simple sentence-ending punctuation (. ! ?) followed by space or end.
    
    Args:
        text: Text to split
        max_len: Maximum length per chunk
        
    Returns:
        List of text chunks, each <= max_len
    """
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    # Split on sentence boundaries: . ! ? followed by space or end of string
    # Use lookahead to keep the punctuation with the sentence
    sentence_pattern = re.compile(r'([.!?])(?:\s+|$)')
    
    # Find all sentence boundaries
    parts = sentence_pattern.split(text)
    
    current_chunk = ""
    i = 0
    while i < len(parts):
        part = parts[i]
        
        # Check if this is punctuation
        if part in ['.', '!', '?']:
            if current_chunk:
                current_chunk += part
            i += 1
            continue
        
        # If adding this part would exceed max_len, save current chunk
        test_chunk = current_chunk + (" " if current_chunk else "") + part
        if current_chunk and len(test_chunk) > max_len:
            chunks.append(current_chunk.strip())
            current_chunk = part
        else:
            if current_chunk:
                current_chunk += " " + part
            else:
                current_chunk = part
        
        i += 1
    
    # Add remaining chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # If any chunk is still too long (no sentence boundaries), hard-split on words
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            final_chunks.append(chunk)
        else:
            # Hard split on word boundaries
            words = chunk.split()
            current = ""
            for word in words:
                test = current + (" " if current else "") + word
                if current and len(test) > max_len:
                    final_chunks.append(current)
                    current = word
                else:
                    current = test
            if current:
                final_chunks.append(current)
    
    return final_chunks if final_chunks else [text[:max_len]]


def _build_xpath(element: Tag) -> str:
    """
    Build a rough XPath from element to root.
    Format: /tag[index]/tag[index]/...
    
    Args:
        element: BeautifulSoup Tag element
        
    Returns:
        XPath string starting with /
    """
    path_parts = []
    current = element
    
    # Traverse up to root
    while current and current.name != '[document]':
        if isinstance(current, Tag) and current.name:
            tag_name = current.name
            
            # Count siblings with same tag name before this element
            index = 1
            if current.parent:
                for sibling in current.parent.children:
                    if sibling is current:
                        break
                    if isinstance(sibling, Tag) and sibling.name == tag_name:
                        index += 1
            
            path_parts.insert(0, f"{tag_name}[{index}]")
        
        current = current.parent
    
    # Build XPath string
    xpath = '/' + '/'.join(path_parts)
    return xpath


def parse_dom(dom: str, max_chunk_len: int | None = None) -> List[Chunk]:
    """
    Parse DOM and extract visible text chunks from block-level elements.
    
    Args:
        dom: HTML string
        max_chunk_len: Maximum chunk length in characters. If None, loads from config.
        
    Returns:
        List of Chunk objects with extracted text
    """
    # Load config if max_chunk_len not provided
    if max_chunk_len is None:
        config = load_config()
        max_chunk_len = config.get("parser", {}).get("max_chunk_len", 1200)
    
    # Try lxml first, fallback to html.parser (built-in)
    try:
        soup = BeautifulSoup(dom, 'lxml')
    except Exception:
        soup = BeautifulSoup(dom, 'html.parser')
    chunks = []
    
    # Block-level tags to extract text from
    block_tags = ['p', 'li', 'section', 'article', 'div', 'td', 'th']
    
    chunk_id = 0
    for tag_name in block_tags:
        for element in soup.find_all(tag_name):
            # Get visible text (strips script/style content automatically)
            text = element.get_text(separator=' ', strip=True)
            
            # Skip empty elements
            if not text or not text.strip():
                continue
            
            # Trim whitespace
            text = ' '.join(text.split())
            
            # Find nearest heading
            heading = _find_nearest_heading(element)
            
            # Extract node identifier
            node_id = _extract_node_id(element)
            
            # Build XPath
            xpath = _build_xpath(element)
            
            # Split text if it exceeds max_chunk_len
            text_chunks = _split_text_on_sentences(text, max_chunk_len)
            
            # Create a chunk for each text piece
            for i, text_chunk in enumerate(text_chunks):
                chunk = Chunk(
                    id=f"{chunk_id}" if len(text_chunks) == 1 else f"{chunk_id}.{i}",
                    text=text_chunk,
                    heading=heading,
                    node_id=node_id,
                    xpath=xpath
                )
                chunks.append(chunk)
            
            chunk_id += 1
    
    return chunks

