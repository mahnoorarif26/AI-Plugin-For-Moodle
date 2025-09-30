from pypdf import PdfReader
from io import BytesIO

def extract_pdf_text(file_storage) -> str:
    """
    Extract text from an uploaded PDF (Flask FileStorage).
    Soft-clamp to ~70k chars to keep prompts manageable.
    """
    data = file_storage.read()
    reader = PdfReader(BytesIO(data))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n\n".join(pages)
    return text[:70000]

def split_into_chunks(text: str, chunk_size: int = 3500) -> list[str]:
    """Break text into smaller chunks for LLM input."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
