import io
import json
import re
from typing import Any, Dict, List, Tuple, Optional

from PyPDF2 import PdfReader


def parse_json_from_str_or_file(data_or_bytes: Any) -> Dict[str, Any]:
    """Parse JSON from a dict, string, or file bytes."""
    if isinstance(data_or_bytes, dict):
        return data_or_bytes
    if isinstance(data_or_bytes, (bytes, bytearray)):
        return json.loads(data_or_bytes.decode('utf-8', errors='ignore'))
    if isinstance(data_or_bytes, str):
        return json.loads(data_or_bytes)
    raise ValueError('Unsupported JSON input type')


def extract_pdf_text_from_file(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyPDF2 (simple text extraction)."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        texts: List[str] = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            texts.append(t)
        return "\n".join(texts)
    except Exception:
        return ""


_Q_SPLIT_PATTERNS = [
    re.compile(r"^\s*(?:Q|Question)\s*(\d+)\s*[:\).\-]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(\d+)\s*[\).:\-]", re.MULTILINE),
]


def _split_pdf_into_segments(text: str) -> List[Tuple[Optional[int], str]]:
    if not text:
        return []
    for pat in _Q_SPLIT_PATTERNS:
        matches = list(pat.finditer(text))
        if len(matches) >= 1:
            segments: List[Tuple[Optional[int], str]] = []
            for i, m in enumerate(matches):
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                try:
                    num = int(m.group(1))
                except Exception:
                    num = None
                segments.append((num, text[start:end].strip()))
            if segments:
                return segments
    # fallback: paragraph-ish blocks
    rough = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
    return [(None, s) for s in rough]


def _extract_mcq_answer(seg: str) -> Optional[str]:
    m = re.search(r"\b([ABCD])\b", seg, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r"Answer\s*[:\-]?\s*([ABCD])\b", seg, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def _extract_tf_answer(seg: str) -> Optional[str]:
    if re.search(r"\btrue\b", seg, re.IGNORECASE):
        return "True"
    if re.search(r"\bfalse\b", seg, re.IGNORECASE):
        return "False"
    return None


def _extract_freeform(seg: str) -> str:
    return re.sub(r"^(Answer\s*[:\-]?)", "", seg.strip(), flags=re.IGNORECASE).strip()


def responses_from_pdf_text(pdf_text: str, quiz: Dict[str, Any]) -> Dict[str, Any]:
    """Map PDF text to responses by question order (heuristic)."""
    segments = _split_pdf_into_segments(pdf_text)
    qlist = list(quiz.get('questions') or [])
    if len(segments) < len(qlist):
        segments = segments + [(None, "")] * (len(qlist) - len(segments))
    out: Dict[str, Any] = {}
    for idx, q in enumerate(qlist):
        qid = q.get('id')
        qtype = (q.get('type') or '').strip().lower()
        seg_text = segments[idx][1] if idx < len(segments) else ""
        if qtype == 'mcq':
            ans = _extract_mcq_answer(seg_text) or _extract_mcq_answer(pdf_text)
            out[qid] = ans
        elif qtype in {'true_false', 'truefalse', 'tf'}:
            ans = _extract_tf_answer(seg_text) or _extract_tf_answer(pdf_text)
            out[qid] = ans
        else:
            out[qid] = _extract_freeform(seg_text)
    return out
