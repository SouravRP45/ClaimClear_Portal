"""
pdf_extractor.py — PDF text extraction with PyMuPDF and OCR fallback
"""
import io
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import logging

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extracts text from PDF bytes with layout awareness and OCR fallback."""

    def validate_pdf(self, pdf_bytes: bytes, max_size_mb: float = 10.0) -> None:
        """
        Validates the PDF file before processing.
        Raises ValueError with user-friendly messages for any issue.
        """
        # Check file size
        size_mb = len(pdf_bytes) / (1024 * 1024)
        if size_mb > max_size_mb:
            raise ValueError(
                f"File is too large ({size_mb:.1f} MB). "
                f"Maximum allowed size is {max_size_mb} MB. "
                "Please compress your PDF and try again."
            )

        # Check PDF magic bytes
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError(
                "The uploaded file does not appear to be a valid PDF. "
                "Please upload a PDF file (must start with %PDF header). "
                "If your file is a Word document, please export it as PDF first."
            )

        # Try opening to detect corruption / password protection
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.is_encrypted:
                raise ValueError(
                    "The PDF is password-protected. "
                    "Please remove the password protection and try again."
                )
            doc.close()
        except fitz.FileDataError as e:
            raise ValueError(
                f"The PDF file appears to be corrupted and cannot be read. "
                f"Technical detail: {str(e)}"
            )

    def extract_text(self, pdf_bytes: bytes) -> tuple[str, list[dict]]:
        """
        Extracts text from PDF bytes with layout-aware reading order.

        Returns:
            full_text: All pages concatenated with [PAGE N] markers
            pages: List of per-page dicts with page_num, text, blocks, ocr_used
        """
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise ValueError(f"Cannot open PDF: {str(e)}")

        pages_data: list[dict] = []
        full_text_parts: list[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_label = f"[PAGE {page_num + 1}]"
            ocr_used = False

            # ── Primary extraction: layout-aware blocks ──────────────────────
            try:
                blocks = page.get_text("blocks")
                # Each block: (x0, y0, x1, y1, text, block_no, block_type)
                # Sort by y0 then x0 for natural reading order
                text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text
                text_blocks.sort(key=lambda b: (b[1], b[0]))  # sort by (y0, x0)
                page_text = "\n".join(b[4].strip() for b in text_blocks if b[4].strip())
            except Exception:
                page_text = ""

            # ── OCR fallback for image-based / scanned pages ─────────────────
            if not page_text.strip():
                logger.info(f"Page {page_num + 1} has no extractable text — attempting OCR")
                try:
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    pil_image = Image.open(io.BytesIO(img_bytes))
                    page_text = pytesseract.image_to_string(pil_image, config="--psm 6")
                    ocr_used = True
                    logger.info(f"OCR succeeded for page {page_num + 1}: {len(page_text)} chars extracted")
                except Exception as ocr_err:
                    logger.warning(f"OCR failed for page {page_num + 1}: {ocr_err}")
                    page_text = ""

            page_entry = {
                "page_num": page_num + 1,
                "text": page_text,
                "blocks": blocks if not ocr_used else [],
                "ocr_used": ocr_used,
            }
            pages_data.append(page_entry)

            if page_text.strip():
                full_text_parts.append(f"{page_label}\n{page_text}")

        doc.close()

        full_text = "\n\n".join(full_text_parts)

        if not full_text.strip():
            raise ValueError(
                "No text could be extracted from this PDF. "
                "The file may be a scanned image with unreadable quality, "
                "or all content may be embedded as graphics. "
                "Please try a clearer scan or a text-based PDF."
            )

        logger.info(
            f"Extracted {len(full_text)} characters from {len(pages_data)} pages "
            f"({sum(1 for p in pages_data if p['ocr_used'])} pages used OCR)"
        )
        return full_text, pages_data
