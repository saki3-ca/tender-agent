"""
Document parser module for PDF, DOCX, and XLSX files.
Extracts text with page numbering, computes document hash, detects scanned pages,
and applies Tesseract OCR (eng+ben) when applicable.
"""

import io
import hashlib
from typing import Any, Dict, List, Optional
from app.utils.logging import logger

# PDF Plumber
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# DOCX
try:
    import docx
except ImportError:
    docx = None

# XLSX
try:
    import openpyxl
except ImportError:
    openpyxl = None

# OCR
try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None


def compute_bytes_hash(content: bytes) -> str:
    """Computes SHA-256 hash of document binary content."""
    return hashlib.sha256(content).hexdigest()


class DocumentParser:
    """Parses tender documents in PDF, DOCX, and XLSX formats."""

    @staticmethod
    def parse_pdf(file_bytes: bytes) -> Dict[str, Any]:
        """
        Parses a PDF document.
        Returns:
            {
                "document_hash": str,
                "total_pages": int,
                "pages": [{"page": 1, "text": str}],
                "full_text": str,
                "is_scanned": bool,
                "ocr_applied": bool
            }
        """
        doc_hash = compute_bytes_hash(file_bytes)
        pages_data: List[Dict[str, Any]] = []
        is_scanned = False
        ocr_applied = False

        if not pdfplumber:
            logger.warning("pdfplumber not installed; cannot extract PDF text directly")
            return {
                "document_hash": doc_hash,
                "total_pages": 0,
                "pages": [],
                "full_text": "",
                "is_scanned": True,
                "ocr_applied": False
            }

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                total_pages = len(pdf.pages)
                for idx, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    # Check if page is predominantly scanned/image
                    if len(text.strip()) < 40 and pytesseract:
                        try:
                            # Render page to image and OCR
                            img = page.to_image(resolution=200).original
                            ocr_text = pytesseract.image_to_string(img, lang="eng+ben")
                            if len(ocr_text.strip()) > len(text.strip()):
                                text = ocr_text
                                ocr_applied = True
                                is_scanned = True
                        except Exception as ocr_err:
                            logger.warning(f"OCR failed on page {idx}: {ocr_err}")
                            is_scanned = True
                    elif len(text.strip()) < 40:
                        is_scanned = True

                    pages_data.append({"page": idx, "text": text.strip()})

            full_text = "\n\n".join([f"--- Page {p['page']} ---\n{p['text']}" for p in pages_data])
            return {
                "document_hash": doc_hash,
                "total_pages": total_pages,
                "pages": pages_data,
                "full_text": full_text,
                "is_scanned": is_scanned,
                "ocr_applied": ocr_applied
            }
        except Exception as e:
            logger.error(f"Error parsing PDF document: {e}", extra={"error": str(e)})
            return {
                "document_hash": doc_hash,
                "total_pages": 0,
                "pages": [],
                "full_text": "",
                "is_scanned": True,
                "ocr_applied": False
            }

    @staticmethod
    def parse_docx(file_bytes: bytes) -> Dict[str, Any]:
        """Parses DOCX documents into page/paragraph text."""
        doc_hash = compute_bytes_hash(file_bytes)
        if not docx:
            return {"document_hash": doc_hash, "pages": [], "full_text": "", "total_pages": 0}

        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            full_text = "\n".join(paragraphs)
            return {
                "document_hash": doc_hash,
                "total_pages": 1,
                "pages": [{"page": 1, "text": full_text}],
                "full_text": full_text,
                "is_scanned": False,
                "ocr_applied": False
            }
        except Exception as e:
            logger.error(f"Error parsing DOCX document: {e}")
            return {"document_hash": doc_hash, "pages": [], "full_text": "", "total_pages": 0}

    @staticmethod
    def parse_xlsx(file_bytes: bytes) -> Dict[str, Any]:
        """Parses XLSX spreadsheets into structured text."""
        doc_hash = compute_bytes_hash(file_bytes)
        if not openpyxl:
            return {"document_hash": doc_hash, "pages": [], "full_text": "", "total_pages": 0}

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            lines = []
            for sheetname in wb.sheetnames:
                ws = wb[sheetname]
                lines.append(f"--- Sheet: {sheetname} ---")
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                    if row_vals:
                        lines.append(" | ".join(row_vals))
            full_text = "\n".join(lines)
            return {
                "document_hash": doc_hash,
                "total_pages": len(wb.sheetnames),
                "pages": [{"page": 1, "text": full_text}],
                "full_text": full_text,
                "is_scanned": False,
                "ocr_applied": False
            }
        except Exception as e:
            logger.error(f"Error parsing XLSX document: {e}")
            return {"document_hash": doc_hash, "pages": [], "full_text": "", "total_pages": 0}
