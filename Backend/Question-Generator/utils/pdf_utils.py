import re
from typing import List, Dict, Any, Tuple
from pypdf import PdfReader
from io import BytesIO

class SmartPDFProcessor:
    def __init__(self, max_chars: int = 70000, target_chunk_size: int = 3500, chunk_overlap: int = 200):
        self.max_chars = max_chars
        self.target_chunk_size = target_chunk_size
        self.chunk_overlap = chunk_overlap
    
    def extract_pdf_text(self, file_storage) -> Tuple[str, Dict[str, Any]]:
            data = file_storage.read()
            reader = PdfReader(BytesIO(data))
        
            document_analysis = {
                'total_pages': len(reader.pages),
                'pages': [],
                'structure_score': 0.0,
                'estimated_tokens': 0
            }
            
            full_text = ""
            page_texts = []
            
            for page_num, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                    
                    # ✅ Preserve newlines for structural analysis
                    # Collapse horizontal whitespace (spaces/tabs) but keep \n
                    page_text = re.sub(r'[^\S\r\n]+', ' ', page_text).strip()
                    
                    if page_text:
                        # Analyze page structure
                        structure_features = self._analyze_page_structure(page_text)
                        page_info = {
                            'page_num': page_num + 1,
                            'text': page_text,
                            'tokens_est': len(page_text) // 4,
                            'has_headings': structure_features['has_headings'],
                            'paragraph_count': structure_features['paragraph_count'],
                            'structure_score': structure_features['structure_score']
                        }
                        
                        page_texts.append(page_info)
                        full_text += page_text + "\n\n"
                        
                except Exception as e:
                    print(f"Error processing page {page_num}: {e}")
                    page_texts.append({
                        'page_num': page_num + 1,
                        'text': '',
                        'tokens_est': 0,
                        'has_headings': False,
                        'paragraph_count': 0,
                        'structure_score': 0.0
                    })
            
            # Smart truncation if needed
            if len(full_text) > self.max_chars:
                full_text = self._smart_truncate(full_text, page_texts)
            
            document_analysis['pages'] = page_texts
            document_analysis['estimated_tokens'] = len(full_text) // 4
            document_analysis['structure_score'] = self._calculate_overall_structure_score(page_texts)
            
            return full_text, document_analysis

    
    def _analyze_page_structure(self, text: str) -> Dict[str, Any]:
        """Analyze how structured the page content is."""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Detect headings
        heading_count = sum(1 for line in lines if self._is_likely_heading(line))
        has_headings = heading_count > 0
        
        # Count paragraphs (roughly)
        paragraphs = [p for p in text.split('\n\n') if len(p.strip()) > 30]
        paragraph_count = len(paragraphs)
        
        # Calculate structure score for this page
        structure_score = 0.0
        if len(lines) > 0:
            # Points for having headings
            if has_headings:
                structure_score += 0.4
            
            # Points for good paragraph structure
            if paragraph_count >= 3:
                structure_score += 0.4
            elif paragraph_count >= 1:
                structure_score += 0.2
            
            # Points for varied line lengths (indicates structure)
            avg_line_len = sum(len(line) for line in lines) / len(lines)
            if 20 < avg_line_len < 100:  # Reasonable text line lengths
                structure_score += 0.2
        
        return {
            'has_headings': has_headings,
            'heading_count': heading_count,
            'paragraph_count': paragraph_count,
            'line_count': len(lines),
            'structure_score': min(structure_score, 1.0)
        }
    
    def _is_likely_heading(self, line: str) -> bool:
        """Heuristic to detect headings."""
        line = line.strip()
        if len(line) < 80:  # Headings are usually shorter
            # Common heading patterns
            patterns = [
                r'^\d+[\.\)]\s+\w+',  # "1. Introduction"
                r'^\b(?:CHAPTER|SECTION|ABSTRACT|INTRODUCTION|METHODOLOGY|RESULTS|CONCLUSION|REFERENCES)\b',
                r'^[A-Z][A-Z\s]{2,}[A-Z]$',  # ALL CAPS lines
                r'^\s*\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$',  # Title Case
            ]
            
            for pattern in patterns:
                if re.match(pattern, line, re.IGNORECASE):
                    return True
            
            # Short lines with few words might be headings
            words = line.split()
            if 2 <= len(words) <= 8 and len(line) < 60:
                return True
        
        return False
    
    def _calculate_overall_structure_score(self, page_texts: List[Dict]) -> float:
        """Calculate overall document structure score (0-1)."""
        if not page_texts:
            return 0.0
        
        valid_pages = [p for p in page_texts if p.get('tokens_est', 0) > 100]
        if not valid_pages:
            return 0.0
        
        structured_pages = sum(1 for p in valid_pages if p.get('has_headings', False))
        avg_structure_score = sum(p.get('structure_score', 0) for p in valid_pages) / len(valid_pages)
        
        overall_score = (structured_pages / len(valid_pages) * 0.6 + avg_structure_score * 0.4)
        return min(overall_score, 1.0)
    
    def _smart_truncate(self, text: str, page_texts: List[Dict]) -> str:
        """
        Smart truncation that preserves important sections.
        Prioritizes beginning content and maintains coherence.
        """
        max_chars = self.max_chars
        
        # Calculate structure score to decide strategy
        structure_score = self._calculate_overall_structure_score(page_texts)
        
        if structure_score > 0.6:  # Well-structured document
            # For structured docs, keep beginning (usually has intro/important content)
            keep_ratio = 0.75
        else:  # Less structured - might be continuous text
            # Keep more of the beginning
            keep_ratio = 0.85
        
        target_chars = int(max_chars * keep_ratio)
        truncated = text[:target_chars]
        
        # Try to end at a paragraph boundary for coherence
        last_paragraph = truncated.rfind('\n\n')
        if last_paragraph > target_chars * 0.8:  # If we're close to a boundary
            truncated = truncated[:last_paragraph]
        
        return truncated
    def _add_overlap(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add character-level overlap between consecutive chunks.
        This helps preserve context across chunk boundaries.
        """
        if not chunks or self.chunk_overlap <= 0:
            return chunks

        overlapped: List[Dict[str, Any]] = []
        prev_text = ""

        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            if i == 0:
                # first chunk unchanged
                overlapped.append(chunk)
            else:
                # take tail from previous chunk and prepend
                tail = prev_text[-self.chunk_overlap:]
                new_text = (tail + "\n\n" + text).strip()
                new_chunk = dict(chunk)
                new_chunk["text"] = new_text
                overlapped.append(new_chunk)

            prev_text = overlapped[-1]["text"]

        return overlapped

    def adaptive_chunking(self, text: str, document_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Adaptive chunking based on document structure analysis.
        Returns chunks with metadata for better retrieval.
        """
        structure_score = document_analysis.get('structure_score', 0.0)
        
        if structure_score > 0.6:
            # Well-structured document - use section-aware chunking
            chunks = self._section_aware_chunking(text)
        elif structure_score > 0.3:
            # Moderately structured - use paragraph chunking
            chunks = self._paragraph_chunking(text)
        else:
            # Poorly structured - use sentence-aware chunking
            chunks = self._sentence_aware_chunking(text)
        
        # Add metadata to each chunk
        for i, chunk in enumerate(chunks):
            chunk['chunk_id'] = i
            chunk['token_estimate'] = len(chunk['text']) // 4
            chunk['structure_type'] = self._classify_chunk_structure(chunk['text'])
        
        return chunks
    
    def _section_aware_chunking(self, text: str) -> List[Dict[str, Any]]:
        """Chunk by sections for well-structured documents."""
        # Enhanced section splitting patterns
        section_patterns = [
            r'\n\s*\d+[\.\)]\s+[A-Z]',  # "1. Introduction"
            r'\n\s*[A-Z][A-Z\s]{5,}[A-Z]\s*\n',  # ALL CAPS headings
            r'\n\s*(?:CHAPTER|SECTION|ABSTRACT|INTRODUCTION|METHOD|RESULTS?|CONCLUSION|REFERENCES?)\b',
            r'\n\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*\n',  # Title Case headings
        ]
        
        # Combine patterns
        combined_pattern = '|'.join(f'({pattern})' for pattern in section_patterns)
        
        chunks = []
        current_chunk = ""
        current_section = "Introduction"
        
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Check if this line is a section header
            is_heading = self._is_likely_heading(line)
            
            if is_heading and current_chunk:
                # Save current chunk if we have content
                if len(current_chunk.strip()) > 50:
                    chunks.append({
                        'text': current_chunk.strip(),
                        'section': current_section,
                        'chunk_type': 'section'
                    })
                current_chunk = line + " "
                current_section = line
            else:
                current_chunk += line + " "
            
            # If current chunk is getting too large, split it
            if len(current_chunk) > self.target_chunk_size:
                if current_chunk.strip():
                    # Split the large chunk
                    sub_chunks = self._split_large_chunk(current_chunk, current_section)
                    if sub_chunks:
                        chunks.extend(sub_chunks[:-1])
                        current_chunk = sub_chunks[-1]['text'] if sub_chunks else ""
        
        # Add the final chunk
                # Add the final chunk
        if current_chunk.strip():
            chunks.append({
                'text': current_chunk.strip(),
                'section': current_section,
                'chunk_type': 'section'
            })
        
        # Add overlap between section chunks for better context
        return self._add_overlap(chunks)

    
    def _paragraph_chunking(self, text: str) -> List[Dict[str, Any]]:
        """Chunk by paragraphs for moderately structured documents."""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip() and len(p.strip()) > 30]
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= self.target_chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    chunks.append({
                        'text': current_chunk,
                        'chunk_type': 'paragraph_group'
                    })
                current_chunk = para
        
        if current_chunk:
            chunks.append({
                'text': current_chunk,
                'chunk_type': 'paragraph_group'
            })
        
        # Add overlap between paragraph-based chunks
        return self._add_overlap(chunks)

    
    def _sentence_aware_chunking(self, text: str) -> List[Dict[str, Any]]:
        """Chunk by sentences for poorly structured documents."""
        # Simple sentence splitting (avoid NLTK dependency for FYP)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= self.target_chunk_size:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
            else:
                if current_chunk:
                    chunks.append({
                        'text': current_chunk,
                        'chunk_type': 'sentence_group'
                    })
                current_chunk = sentence
        
        if current_chunk:
            chunks.append({
                'text': current_chunk,
                'chunk_type': 'sentence_group'
            })
        
        # Add overlap between sentence-based chunks
        return self._add_overlap(chunks)

    
    def _split_large_chunk(self, text: str, section: str) -> List[Dict[str, Any]]:
        """Split chunks that are too large."""
        # Try to split by paragraphs first
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        if len(paragraphs) > 1:
            chunks = []
            current_chunk = ""
            
            for para in paragraphs:
                if len(current_chunk) + len(para) + 2 <= self.target_chunk_size:
                    if current_chunk:
                        current_chunk += "\n\n" + para
                    else:
                        current_chunk = para
                else:
                    if current_chunk:
                        chunks.append({
                            'text': current_chunk,
                            'section': section,
                            'chunk_type': 'subsection'
                        })
                    current_chunk = para
            
            if current_chunk:
                chunks.append({
                    'text': current_chunk,
                    'section': section,
                    'chunk_type': 'subsection'
                })
            
            return chunks
        else:
            # Fallback to fixed-size chunking with overlap
            chunks = []
            start = 0
            while start < len(text):
                end = start + self.target_chunk_size
                chunk_text = text[start:end]
                chunks.append({
                    'text': chunk_text,
                    'section': f"{section} (part {len(chunks) + 1})",
                    'chunk_type': 'fixed_split'
                })
                start += self.target_chunk_size - self.chunk_overlap
            
            return chunks
    
    def _classify_chunk_structure(self, chunk_text: str) -> str:
        """Classify what type of content this chunk contains."""
        lines = chunk_text.split('\n')
        if len(lines) > 0 and self._is_likely_heading(lines[0]) and len(chunk_text) < 500:
            return "heading"
        elif len(chunk_text) < 800:
            return "dense"
        else:
            return "normal"

# Legacy functions for backward compatibility
def extract_pdf_text(file_storage) -> str:
    """Legacy function - uses new processor internally."""
    processor = SmartPDFProcessor()
    text, _ = processor.extract_pdf_text(file_storage)
    return text

def split_into_chunks(text: str, chunk_size: int = 3500) -> List[str]:
    """Legacy function - basic chunking for backward compatibility."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]