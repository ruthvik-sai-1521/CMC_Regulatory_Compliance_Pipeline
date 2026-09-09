"""
Shared low-level helpers used by both the dossier parser and the QA parser.

The two source PDFs are "unstructured" in the sense that they are free-form
regulatory documents, but the individual data tables inside them are
consistently formatted. Rather than hardcoding page numbers, every table is
located dynamically by matching its header row against a known signature.
This keeps the pipeline resilient to the tables shifting to different pages
in a re-issued dossier (e.g. an amended version with extra pages).
"""
import re
from typing import Optional


def first_number(text: Optional[str]) -> Optional[float]:
    """Extract the first floating point number found in a string."""
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group()) if match else None


def all_numbers(text: Optional[str]):
    """Extract every floating point number found in a string, in order."""
    if not text:
        return []
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))]


def clean(text: Optional[str]) -> Optional[str]:
    """Collapse internal whitespace/newlines produced by wrapped PDF table cells."""
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip()


def find_table(pages_tables, header_keywords):
    """
    Search every extracted table (across all pages) for the first whose header
    row contains all of `header_keywords` (case-insensitive substring match).

    pages_tables: list of (page_number, table) tuples, table = list[list[str]]
    header_keywords: list[str] that must all appear somewhere in the header row
    """
    for page_no, table in pages_tables:
        if not table:
            continue
        header = " | ".join(c or "" for c in table[0]).lower()
        if all(kw.lower() in header for kw in header_keywords):
            return page_no, table
    return None, None


def rows_after_header(table):
    """Return data rows (everything after the header row), cells cleaned."""
    return [[clean(c) for c in row] for row in table[1:]] if table else []
