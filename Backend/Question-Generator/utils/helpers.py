"""Helper utilities for text processing and document analysis."""

import re
from typing import Dict, List, Any


def get_chunk_types_distribution(chunks_with_metadata: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Helper method to analyze chunk type distribution for FYP analysis.
    
    Args:
        chunks_with_metadata: List of chunks with metadata
        
    Returns:
        dict: Distribution of chunk types
    """
    distribution = {}
    for chunk in chunks_with_metadata:
        chunk_type = chunk.get('chunk_type', 'unknown')
        distribution[chunk_type] = distribution.get(chunk_type, 0) + 1
    return distribution


def is_likely_heading(line: str) -> bool:
    """
    Helper function to detect likely headings.
    
    Args:
        line: Text line to analyze
        
    Returns:
        bool: True if the line is likely a heading
    """
    line = line.strip()
    if len(line) < 80:
        patterns = [
            r'^\d+[\.\)]\s+\w+',
            r'^\b(?:CHAPTER|SECTION|ABSTRACT|INTRODUCTION|METHODOLOGY|RESULTS|CONCLUSION|REFERENCES)\b',
            r'^[A-Z][A-Z\s]{2,}[A-Z]$',
            r'^\s*\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$',
        ]
        for pattern in patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        words = line.split()
        if 2 <= len(words) <= 8 and len(line) < 60:
            return True
    return False


def get_enhanced_fallback_subtopics(raw_text: str, document_analysis: Dict[str, Any]) -> List[str]:
    """
    Enhanced fallback subtopic extraction using document structure analysis.
    
    Args:
        raw_text: Raw document text
        document_analysis: Document analysis metadata
        
    Returns:
        list: List of extracted subtopics
    """
    subtopics = []
    
    # Method 1: Extract from page analysis
    for page in document_analysis.get('pages', []):
        if page.get('has_headings') and page.get('text'):
            lines = [line.strip() for line in page['text'].split('\n') if line.strip()]
            for line in lines:
                if is_likely_heading(line) and line not in subtopics:
                    subtopics.append(line)
    
    # Method 2: Extract numbered sections
    numbered_sections = re.findall(r'\n\s*(\d+[\.\)]\s+[^\n]{5,50})', raw_text)
    subtopics.extend(numbered_sections[:5])
    
    # Method 3: Extract ALL CAPS headings
    all_caps_headings = re.findall(r'\n\s*([A-Z][A-Z\s]{5,30}[A-Z])\s*\n', raw_text)
    subtopics.extend(all_caps_headings[:3])
    
    # Method 4: Extract title case lines (potential section headers)
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    for line in lines[:50]:  # Check first 50 lines
        words = line.split()
        if 2 <= len(words) <= 8 and len(line) < 80:
            # Check if it's title case or has other heading characteristics
            if (any(word.istitle() for word in words if len(word) > 3) or 
                re.match(r'^\d+[\.\)]', line)):
                if line not in subtopics:
                    subtopics.append(line)
    
    # Remove duplicates and clean up
    unique_subtopics = list(dict.fromkeys([s.strip() for s in subtopics if s.strip()]))
    
    # Ensure we have some subtopics
    if not unique_subtopics:
        # Final fallback: use first sentences from important paragraphs
        paragraphs = [p.strip() for p in raw_text.split('\n\n') if len(p.strip()) > 50]
        for para in paragraphs[:5]:
            first_sentence = para.split('.')[0] + '.'
            if len(first_sentence) > 20 and len(first_sentence) < 100:
                unique_subtopics.append(first_sentence)
    
    return unique_subtopics[:10]