"""
file_processor.py
------------------
Turns an uploaded file (PDF, PNG, JPG, JPEG, WEBP, TIFF, BMP) into a list of
LangChain Document objects, ready to be chunked + embedded.

Handles three cases:
  1. Digital / text-based PDFs        -> plain text extraction (pypdf)
  2. Scanned / image-only PDF pages   -> page rendered to an image, then OCR'd
  3. Photos of handwritten/printed
     pages, prescriptions, lab charts -> OCR'd directly

OCR is performed primarily with Gemini's multimodal vision model (it reads
messy handwriting, tables and prescriptions far better than classic OCR
engines), with a local Tesseract fallback so the app still works when the
Gemini call fails or the OCR_ENGINE env var is set to "tesseract".
"""

import base64
import io
import os
from typing import List, Tuple

from langchain.schema import Document
from pypdf import PdfReader
from PIL import Image

from src import gemini_client

OCR_PROMPT = (
    "You are an OCR engine for a document assistant. "
    "Transcribe ALL text visible in this image exactly as written — "
    "printed text, handwriting, prescriptions, lab values, tables and "
    "stamps included. Keep the original structure/line breaks where it "
    "helps readability (e.g. keep table rows together). "
    "If a word is illegible, write [illegible] instead of guessing wildly. "
    "Do not add commentary, translation, explanation or markdown fences — "
    "output ONLY the transcribed text."
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}
MIN_CHARS_FOR_DIGITAL_PAGE = 25  # below this we assume the PDF page is a scanned image

OCR_ENGINE = os.environ.get("OCR_ENGINE", "gemini").lower()  # "gemini" | "tesseract"


def _image_to_base64_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _ocr_with_gemini(img: Image.Image, api_key: str) -> str:
    """Use the Gemini REST API directly for OCR (no langchain wrapper)."""
    b64 = _image_to_base64_png(img)
    return gemini_client.generate_from_image(
        api_key=api_key,
        prompt=OCR_PROMPT,
        image_b64=b64,
        mime_type="image/png",
    )


def _ocr_with_tesseract(img: Image.Image) -> str:
    import pytesseract

    return pytesseract.image_to_string(img).strip()


def _ocr_image(img: Image.Image, api_key: str) -> Tuple[str, str]:
    """Returns (text, engine_used). Falls back to tesseract if Gemini fails."""
    if OCR_ENGINE == "tesseract":
        try:
            return _ocr_with_tesseract(img), "tesseract"
        except Exception as e:
            return f"[OCR failed: {e}]", "tesseract-error"

    try:
        text = _ocr_with_gemini(img, api_key)
        if text:
            return text, "gemini-vision"
        raise ValueError("empty OCR result")
    except Exception:
        try:
            return _ocr_with_tesseract(img), "tesseract-fallback"
        except Exception as e:
            return f"[OCR failed on both engines: {e}]", "failed"


def _process_pdf(path: str, filename: str, api_key: str) -> Tuple[List[Document], bool]:
    """Extracts text page by page; OCRs any page that looks like a scanned image."""
    docs: List[Document] = []
    used_ocr = False

    reader = PdfReader(path)
    scanned_page_indices = []

    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if len(text) >= MIN_CHARS_FOR_DIGITAL_PAGE:
            docs.append(
                Document(
                    page_content=text,
                    metadata={"source": filename, "page": i + 1, "ocr": False},
                )
            )
        else:
            scanned_page_indices.append(i)

    if scanned_page_indices:
        try:
            from pdf2image import convert_from_path

            for i in scanned_page_indices:
                images = convert_from_path(
                    path, first_page=i + 1, last_page=i + 1, dpi=200
                )
                if not images:
                    continue
                text, engine = _ocr_image(images[0], api_key)
                used_ocr = True
                if text:
                    docs.append(
                        Document(
                            page_content=text,
                            metadata={
                                "source": filename,
                                "page": i + 1,
                                "ocr": True,
                                "ocr_engine": engine,
                            },
                        )
                    )
        except Exception as e:
            docs.append(
                Document(
                    page_content=(
                        f"[Page(s) {[p + 1 for p in scanned_page_indices]} appear to be "
                        f"scanned images and could not be OCR'd: {e}. "
                        "Install poppler-utils for scanned-PDF support.]"
                    ),
                    metadata={"source": filename, "page": -1, "ocr": False},
                )
            )

    return docs, used_ocr


def _process_image(path: str, filename: str, api_key: str) -> Tuple[List[Document], bool]:
    img = Image.open(path)
    text, engine = _ocr_image(img, api_key)
    doc = Document(
        page_content=text or "[No text detected in image]",
        metadata={"source": filename, "page": 1, "ocr": True, "ocr_engine": engine},
    )
    return [doc], True


def process_uploaded_file(path: str, filename: str, api_key: str) -> Tuple[List[Document], bool]:
    """
    Main entry point. Returns (documents, used_ocr).
    Raises ValueError for unsupported file types.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        return _process_pdf(path, filename, api_key)
    elif ext in IMAGE_EXTENSIONS:
        return _process_image(path, filename, api_key)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
