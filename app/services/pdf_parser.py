"""PDF parser — Layer 1 of the normalisation engine.

Extracts tables and text from PDF management packs using pdfplumber.
"""

import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


class PDFParser:
    """Extracts text and table data from PDF files."""

    def parse(self, file_bytes: bytes) -> str:
        """Parse a PDF file into a text representation.

        Strategy:
        1. Extract tables first (most useful for financial data).
        2. Extract running text for context (commentary, notes).
        3. Combine into a single text block for the LLM.
        """
        sections: list[str] = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            logger.info("Parsing PDF: %d pages", len(pdf.pages))

            for i, page in enumerate(pdf.pages):
                page_sections: list[str] = []

                # Extract tables
                tables = page.extract_tables()
                if tables:
                    for t_idx, table in enumerate(tables):
                        table_text = f"--- Table {t_idx + 1} (Page {i + 1}) ---\n"
                        for row in table:
                            cleaned = [str(cell).strip() if cell else "" for cell in row]
                            table_text += " | ".join(cleaned) + "\n"
                        page_sections.append(table_text)

                # Extract running text (excluding table content to avoid duplication)
                text = page.extract_text()
                if text and text.strip():
                    # Only add text if we didn't find tables, or if text adds context
                    if not tables:
                        page_sections.append(f"--- Text (Page {i + 1}) ---\n{text.strip()}")
                    else:
                        # Add text that seems like commentary (not just numbers)
                        lines = text.strip().split("\n")
                        commentary = [
                            l for l in lines
                            if len(l) > 30 and not all(c in "0123456789,. |$£€%" for c in l.strip())
                        ]
                        if commentary:
                            page_sections.append(
                                f"--- Commentary (Page {i + 1}) ---\n"
                                + "\n".join(commentary[:20])
                            )

                if page_sections:
                    sections.append("\n".join(page_sections))

        if not sections:
            logger.warning("No content extracted from PDF")
            return "No extractable content found in the PDF."

        result = "\n\n".join(sections)
        logger.info("Extracted %d chars from PDF", len(result))
        return result


# Singleton
pdf_parser = PDFParser()
