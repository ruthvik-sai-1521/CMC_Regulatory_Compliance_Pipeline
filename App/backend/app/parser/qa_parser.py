"""
Parses the Site QA & Batch Audit Record PDF (eBMR audit, finished-product
CoA, nitrosamine trending, process-validation yields, deviation/CAPA log and
disposition sign-off) into structured Python data.
"""
from typing import Any, Dict, List

import pdfplumber

from .utils import all_numbers, clean, find_table, first_number, rows_after_header


def _load_pages_tables(pdf_path: str):
    pages_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                pages_tables.append((i, table))
    return pages_tables


def parse_qa_package(pdf_path: str) -> Dict[str, Any]:
    pages_tables = _load_pages_tables(pdf_path)

    result: Dict[str, Any] = {}
    result["document_metadata_extra"] = _parse_qa_header(pages_tables)
    result["review_summary"] = _parse_review_summary(pages_tables)
    result["ebmr_audit"] = _parse_ebmr(pages_tables)
    result["coa_results"] = _parse_coa(pages_tables)
    result["nitrosamine_levels"] = _parse_nitrosamine(pages_tables)
    result["process_validation_yields"] = _parse_process_validation(pages_tables)
    result["deviations"] = _parse_deviations(pages_tables)
    result["disposition_signoff"] = _parse_disposition(pages_tables)
    return result


def _parse_qa_header(pages_tables) -> Dict[str, Any]:
    # The QA doc header is prose, not a clean table in this layout; leave for
    # future enhancement (e.g. regex over page 1 text) -- non-critical for audit.
    return {}


def _parse_review_summary(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["qa compliance status"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "review_area": row[0],
            "batches_assessed": row[1],
            "qa_compliance_status": row[2],
            "action_required": row[3],
        })
    return rows_out


def _parse_ebmr(pages_tables) -> Dict[str, Dict[str, Any]]:
    _, table = find_table(pages_tables, ["batch 01 (ebmr)"])
    batches: Dict[str, Dict[str, Any]] = {
        "AML-2026-01": {}, "AML-2026-02": {}, "AML-2026-03": {}
    }
    ids = list(batches.keys())
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        key = row[0].lower()
        for idx, bid in enumerate(ids):
            val = row[idx + 2] if idx + 2 < len(row) else None
            if "reflux temp" in key:
                batches[bid]["step1_reflux_temp_c"] = first_number(val)
            elif "agitation" in key:
                batches[bid]["step1_agitation_rpm"] = first_number(val)
            elif "amine addition" in key:
                batches[bid]["step2_amine_addition_temp_c"] = first_number(val)
            elif "deprotection time" in key:
                batches[bid]["step2_deprotection_time_hr"] = first_number(val)
            elif "acid addition" in key:
                batches[bid]["step3_acid_addition_min"] = first_number(val)
    return batches


def _parse_coa(pages_tables) -> Dict[str, Dict[str, Any]]:
    _, table = find_table(pages_tables, ["batch 01 result"])
    batches: Dict[str, Dict[str, Any]] = {
        "AML-2026-01": {}, "AML-2026-02": {}, "AML-2026-03": {}
    }
    ids = list(batches.keys())
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        key = row[0].lower()
        for idx, bid in enumerate(ids):
            val = row[idx + 2] if idx + 2 < len(row) else None
            if "assay" in key:
                batches[bid]["assay_pct"] = first_number(val)
            elif "impurity a" in key:
                batches[bid]["impurity_a_pct"] = first_number(val)
            elif "impurity f" in key:
                batches[bid]["impurity_f_pct"] = first_number(val)
            elif "residual ipa" in key:
                batches[bid]["residual_ipa_ppm"] = first_number(val)
            elif "water content" in key:
                batches[bid]["water_content_pct"] = first_number(val)
    return batches


def _parse_nitrosamine(pages_tables) -> Dict[str, Dict[str, Any]]:
    _, table = find_table(pages_tables, ["ai limit (ppm)"])
    batches: Dict[str, Dict[str, Any]] = {
        "AML-2026-01": {}, "AML-2026-02": {}, "AML-2026-03": {}
    }
    ids = list(batches.keys())
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        key = row[0].lower()
        for idx, bid in enumerate(ids):
            val = row[idx + 2] if idx + 2 < len(row) else None
            n = first_number(val)
            if "nitrosopiperidine" in key:
                batches[bid]["n_nitrosopiperidine_ppm"] = n
            elif "nitroso-amlodipine" in key:
                batches[bid]["n_nitroso_amlodipine_ppm"] = n
            elif "benzenesulfonate" in key:
                batches[bid]["benzenesulfonate_esters_ppm"] = n
    return batches


def _parse_process_validation(pages_tables) -> Dict[str, Dict[str, Any]]:
    _, table = find_table(pages_tables, ["target yield scope"])
    batches: Dict[str, Dict[str, Any]] = {
        "AML-2026-01": {}, "AML-2026-02": {}, "AML-2026-03": {}
    }
    ids = list(batches.keys())
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        key = row[0].lower()
        for idx, bid in enumerate(ids):
            val = row[idx + 2] if idx + 2 < len(row) else None
            n = first_number(val)
            if "cyclization" in key:
                batches[bid]["step1_cyclization_pct"] = n
            elif "deprotection" in key:
                batches[bid]["step2_deprotection_pct"] = n
            elif "salt formation" in key:
                batches[bid]["step3_salt_formation_pct"] = n
            elif "overall process yield" in key:
                batches[bid]["overall_process_yield_pct"] = n
    return batches


def _parse_deviations(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["record id"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "record_id": row[0],
            "affected_batch": row[1],
            "event_description": row[2],
            "severity": row[3],
            "status": row[4],
        })
    return rows_out


def _parse_disposition(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["disposition decision"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "qa_function": row[0],
            "reviewer_name": row[1],
            "disposition_decision": row[2],
            "date_signature": row[3],
        })
    return rows_out
