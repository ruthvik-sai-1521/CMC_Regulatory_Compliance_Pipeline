from .dossier_parser import parse_dossier
from .qa_parser import parse_qa_package
from .schema_mapper import build_regulatory_filing


def parse_and_map(dossier_pdf_path: str, qa_pdf_path: str) -> dict:
    """Full Part 1 pipeline: two PDFs in, one regulatoryFiling.json-shaped dict out."""
    dossier_data = parse_dossier(dossier_pdf_path)
    qa_data = parse_qa_package(qa_pdf_path)
    return build_regulatory_filing(dossier_data, qa_data)


__all__ = ["parse_dossier", "parse_qa_package", "build_regulatory_filing", "parse_and_map"]
