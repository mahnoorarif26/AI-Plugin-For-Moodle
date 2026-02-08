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
        return json.loads(data_or_bytes.decode("utf-8", errors="ignore"))
    if isinstance(data_or_bytes, str):
        return json.loads(data_or_bytes)
    raise ValueError("Unsupported JSON input type")


def extract_pdf_text_from_file(file_bytes: bytes) -> str:
    """
    Extract text from PDF bytes using PyPDF2.
    Adds simple page separators for more reliable segmentation.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        texts: List[str] = []

        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            texts.append(f"--- PAGE {page_num + 1} ---\n{text}")

        return "\n\n".join(texts)
    except Exception:
        return ""


_Q_SPLIT_PATTERNS = [
    # "Q1:", "Q1.", "Q1)", "Question 1:"
    re.compile(
        r"^\s*(?:Q|Question)\s*(\d+)\s*[:\).\-]\s*",
        re.IGNORECASE | re.MULTILINE,
    ),
    # "1.", "1)", "1-", "1:"
    re.compile(r"^\s*(\d+)\s*[\).:\-]\s+", re.MULTILINE),
]


def _find_explicit_answers(text: str) -> Dict[int, str]:
    """
    Find answers explicitly marked in the PDF, e.g. "Answer 1: ...".
    """
    answers: Dict[int, str] = {}

    # Pattern: "Answer 1: ..."
    for match in re.finditer(
        r"(?:Answer|Ans)\s*[:\-]?\s*(\d+)\s*[:\-]\s*(.+?)(?=(?:Answer|Ans)\s*[:\-]?\s*\d+|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        q_num = int(match.group(1))
        answer_text = match.group(2).strip()
        answer_text = answer_text.split("\n\n")[0].strip()
        answers[q_num] = answer_text

    # Pattern: "Q1 Answer: ..."
    for match in re.finditer(
        r"Q\s*(\d+)\s*(?:Answer|:)\s*[:\-]?\s*(.+?)(?=Q\s*\d+|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        q_num = int(match.group(1))
        if q_num not in answers:
            answer_text = match.group(2).strip()
            answer_text = answer_text.split("\n\n")[0].strip()
            answers[q_num] = answer_text

    return answers


def _split_pdf_into_segments(text: str) -> List[Tuple[Optional[int], str]]:
    """
    Split PDF text into question segments.
    Returns list of (question_number, text_segment) tuples.
    """
    if not text:
        return []

    for pat in _Q_SPLIT_PATTERNS:
        matches = list(pat.finditer(text))
        if len(matches) >= 2:
            segments: List[Tuple[Optional[int], str]] = []
            for i, m in enumerate(matches):
                try:
                    num = int(m.group(1))
                except Exception:
                    num = None
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                segment_text = text[start:end].strip()
                segments.append((num, segment_text))
            if segments:
                return segments

    # Fallback: paragraph-level splitting
    paragraphs = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
    return [(None, p) for p in paragraphs]


def _extract_mcq_answer(seg: str) -> Optional[str]:
    """Extract MCQ answer letter (A/B/C/D) from a text segment."""
    m = re.search(r"\b([ABCD])\b", seg, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(
        r"(?:Answer|Ans|Selected)\s*[:\-]?\s*([ABCD])\b", seg, re.IGNORECASE
    )
    if m:
        return m.group(1).upper()
    m = re.search(r"[\[\(][Xx✓✔][\]\)]\s*([ABCD])\b", seg, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def _extract_tf_answer(seg: str) -> Optional[str]:
    """Extract True/False answer from segment."""
    if re.search(r"\bTrue\b", seg, re.IGNORECASE):
        return "True"
    if re.search(r"\bFalse\b", seg, re.IGNORECASE):
        return "False"

    m = re.search(
        r"(?:Answer|Ans)\s*[:\-]?\s*(True|False)\b", seg, re.IGNORECASE
    )
    if m:
        return m.group(1).capitalize()

    m = re.search(r"\b([TF])\b", seg)
    if m:
        return "True" if m.group(1).upper() == "T" else "False"

    return None


def _extract_freeform(seg: str) -> str:
    """
    Extract free-form answer from text segment.
    Strips common prefixes and question repetition.
    """
    cleaned = re.sub(
        r"^(?:Answer|Ans|Response)\s*[:\-]?\s*",
        "",
        seg.strip(),
        flags=re.IGNORECASE,
    )

    sentences = cleaned.split(".")
    if sentences and sentences[0].strip().endswith("?"):
        cleaned = ".".join(sentences[1:]).strip()

    return cleaned.strip()


def responses_from_pdf_text(pdf_text: str, quiz: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map PDF text to responses using multiple strategies:
    1. Explicit "Answer 1: ..." blocks
    2. Question-number based segmentation
    3. Per-question type-specific extraction
    """
    qlist = list(quiz.get("questions") or [])

    explicit_answers = _find_explicit_answers(pdf_text)
    segments = _split_pdf_into_segments(pdf_text)

    if len(segments) < len(qlist):
        segments = segments + [(None, "")] * (len(qlist) - len(segments))

    out: Dict[str, Any] = {}

    for idx, q in enumerate(qlist):
        qid = q.get("id", f"Q{idx + 1}")
        qtype = (q.get("type") or "").strip().lower()

        if (idx + 1) in explicit_answers:
            answer_text = explicit_answers[idx + 1]
        else:
            answer_text = segments[idx][1] if idx < len(segments) else ""

        if qtype == "mcq":
            ans = _extract_mcq_answer(answer_text) or _extract_mcq_answer(
                pdf_text
            )
            out[qid] = ans
        elif qtype in {"true_false", "truefalse", "tf"}:
            ans = _extract_tf_answer(answer_text) or _extract_tf_answer(
                pdf_text
            )
            out[qid] = ans
        else:
            cleaned = _extract_freeform(answer_text)
            out[qid] = cleaned if cleaned else answer_text

    return out
