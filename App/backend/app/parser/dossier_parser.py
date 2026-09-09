"""
Parses the ICH CTD Module 3.2.S regulatory dossier PDF into structured
Python data ready to be merged into the regulatoryFiling.json schema.

Design note: rather than trusting fixed page numbers (which would break the
moment the dossier is re-paginated), every data block is located by matching
its table header row against a known signature via `find_table`.
"""
from typing import Any, Dict, List

import pdfplumber

from .utils import all_numbers, clean, find_table, first_number, rows_after_header


def _load_pages_tables(pdf_path: str):
    pages_tables = []
    full_text_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            full_text_pages.append(page.extract_text() or "")
            for table in page.extract_tables():
                pages_tables.append((i, table))
    return pages_tables, full_text_pages


def parse_dossier(pdf_path: str) -> Dict[str, Any]:
    pages_tables, _ = _load_pages_tables(pdf_path)
    result: Dict[str, Any] = {}

    result["document_metadata"] = _parse_metadata(pages_tables)
    result["drug_substance_profile"] = _parse_drug_substance_profile(pages_tables)
    result["ksm_and_raw_materials"] = _parse_ksm(pages_tables)
    result["process_controls"] = {
        "critical_process_parameters": _parse_cpp_matrix(pages_tables),
        "hold_time_limits": _parse_hold_times(pages_tables),
    }
    result["impurity_profile"] = {
        "organic_impurities": _parse_organic_impurities(pages_tables),
        "residual_solvents": _parse_residual_solvents(pages_tables),
    }
    result["nitrosamine_risk_assessment"] = _parse_nitrosamine_risk(pages_tables)
    result["elemental_impurities"] = _parse_elemental_impurities(pages_tables)
    result["release_specifications"] = _parse_release_specs(pages_tables)
    result["analytical_method_validation"] = _parse_method_validation(pages_tables)
    result["stability_data"] = {
        "forced_degradation": _parse_forced_degradation(pages_tables),
        "long_term_stability": _parse_long_term_stability(pages_tables),
    }
    result["dossier_batch_comparison"] = _parse_batch_comparison(pages_tables)
    return result


def _parse_metadata(pages_tables) -> Dict[str, Any]:
    _, table = find_table(pages_tables, ["submitting entity"])
    meta = {
        "document_id": None,
        "drug_substance": None,
        "dmf_number": None,
        "submitting_entity": None,
        "target_authorities": [],
        "submission_purpose": None,
        "ctd_module_scope": None,
        "effective_date": None,
    }
    if not table:
        return meta
    flat = {}
    for row in table:
        for i in range(0, len(row) - 1, 2):
            key = clean(row[i])
            val = clean(row[i + 1])
            if key:
                flat[key.rstrip(":")] = val
    meta["submitting_entity"] = flat.get("Submitting Entity")
    authorities = flat.get("Target Regulatory Authorities")
    meta["target_authorities"] = [a.strip() for a in authorities.split(",")] if authorities else []
    meta["drug_substance"] = flat.get("Drug Substance (API)")
    meta["dmf_number"] = flat.get("DMF Number")
    meta["submission_purpose"] = flat.get("Submission Purpose")
    meta["ctd_module_scope"] = flat.get("CTD Module Scope")
    meta["document_id"] = flat.get("Document ID / Ref")
    meta["effective_date"] = flat.get("Effective Date / Year")
    return meta


def _parse_drug_substance_profile(pages_tables) -> Dict[str, Any]:
    _, table = find_table(pages_tables, ["specification / empirical value"])
    profile = {
        "iupac_name": None,
        "cas_number_besylate": None,
        "cas_number_free_base": None,
        "molecular_formula": None,
        "molecular_weight": None,
        "stereochemistry": None,
        "melting_point_range_c": None,
        "pka": None,
        "log_p": None,
        "solubility_matrix": [],
    }
    if table:
        rows = {clean(r[0]).rstrip(":"): clean(r[1]) for r in table[1:] if r and r[0]}
        profile["iupac_name"] = rows.get("IUPAC Chemical Name")
        cas = rows.get("CAS Registry Number", "")
        parts = cas.split("/") if cas else []
        profile["cas_number_besylate"] = clean(parts[0]).split(" (")[0] if len(parts) > 0 else None
        profile["cas_number_free_base"] = clean(parts[1]).split(" (")[0] if len(parts) > 1 else None
        profile["molecular_formula"] = rows.get("Molecular Formula & Weight")
        mw = rows.get("Molecular Formula & Weight", "")
        if "g/mol" in mw:
            nums = all_numbers(mw.split("|")[-1])
            profile["molecular_weight"] = f"{nums[0]} g/mol" if nums else None
        profile["stereochemistry"] = rows.get("Stereochemistry")
        profile["melting_point_range_c"] = rows.get("Melting Point / Thermal Transition")
        profile["pka"] = rows.get("Dissociation Constant (pKa)")
        profile["log_p"] = rows.get("Partition Coefficient (Log P)")

    _, sol_table = find_table(pages_tables, ["solvent / buffer media"])
    solubility = []
    for row in rows_after_header(sol_table):
        if not row or not row[0]:
            continue
        solubility.append({
            "media": row[0],
            "ph": row[1],
            "solubility": row[2],
            "classification": row[3],
        })
    profile["solubility_matrix"] = solubility
    return profile


def _parse_ksm(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["material name / cas"])
    materials = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        name_cas = row[0].split("CAS:")
        materials.append({
            "material_name": clean(name_cas[0]),
            "cas_number": clean(name_cas[1]) if len(name_cas) > 1 else None,
            "role": row[1],
            "acceptance_specification": row[2],
            "purge_rationale": row[3],
        })
    return materials


def _parse_cpp_matrix(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["proven acceptable"])
    params = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        params.append({
            "process_step": row[0],
            "parameter": row[1],
            "target": row[2],
            "proven_acceptable_range": row[3],
            "cqa_impact": row[4],
        })
    return params


def _parse_hold_times(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["validated maximum hold"])
    holds = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        holds.append({
            "intermediate_stage": row[0],
            "storage_condition": row[1],
            "max_hold_time": row[2],
            "retest_parameter": row[3],
        })
    return holds


def _parse_organic_impurities(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["impurity name / structure id"])
    impurities = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        name_cas = row[0].split("CAS:")
        impurities.append({
            "impurity_name": clean(name_cas[0]),
            "cas_number": clean(name_cas[1]) if len(name_cas) > 1 else None,
            "origin": row[1],
            "ich_q3a_limit": row[2],
            "proposed_spec": row[3],
            "batch_range_observed": row[4],
        })
    return impurities


def _parse_residual_solvents(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["ich q3c option 1 limit"])
    solvents = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        solvents.append({
            "solvent_name": row[0],
            "ich_class": row[1],
            "ich_q3c_limit": row[2],
            "proposed_qc_spec": row[3],
            "observed_level": row[4],
        })
    return solvents


def _parse_nitrosamine_risk(pages_tables) -> Dict[str, Any]:
    _, table = find_table(pages_tables, ["evaluation factor"])
    risk = {"risk_factors": [], "calculated_ai_ng_per_day": None, "confirmatory_testing_result": None}
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        risk["risk_factors"].append({
            "factor": row[0],
            "finding": row[1],
            "conclusion": row[2],
        })
        if "NDSRI" in (row[0] or ""):
            n = all_numbers(row[2])
            risk["calculated_ai_ng_per_day"] = n[0] if n else None
        if "Confirmatory" in (row[0] or ""):
            risk["confirmatory_testing_result"] = row[2]
    return risk


def _parse_elemental_impurities(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["icp-ms"])
    elements = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        elements.append({
            "element_class": row[0],
            "target_elements": row[1],
            "ich_q3d_pde": row[2],
            "observed_level": row[3],
        })
    return elements


def _parse_release_specs(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["acceptance specification / release threshold"])
    specs = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        specs.append({
            "test_parameter": row[0],
            "test_method_id": row[1],
            "acceptance_specification": row[2],
        })
    return specs


def _parse_method_validation(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["validation parameter"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "validation_parameter": row[0],
            "acceptance_criteria": row[1],
            "assay_result": row[2],
            "related_substances_result": row[3],
        })
    return rows_out


def _parse_forced_degradation(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["stress condition"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "stress_condition": row[0],
            "exposure_parameters": row[1],
            "assay_pct": first_number(row[2]),
            "total_degradants_pct": first_number(row[3]),
            "primary_degradation_product": row[4],
        })
    return rows_out


def _parse_long_term_stability(pages_tables) -> List[Dict[str, Any]]:
    _, table = find_table(pages_tables, ["18 months"])
    rows_out = []
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        rows_out.append({
            "test_parameter": row[0],
            "initial_t0": row[1],
            "month_6": row[2],
            "month_12": row[3],
            "month_18": row[4],
            "month_24": row[5],
            "specification": row[6],
        })
    return rows_out


def _parse_batch_comparison(pages_tables) -> Dict[str, Dict[str, Any]]:
    """
    Page 14 commercial batch comparison table -- this is the dossier's own
    (self-reported) view of batch quality, kept separate from the
    independently audited QA CoA data so the rule engine can cross-check them.
    """
    _, table = find_table(pages_tables, ["lot # aml-2026-01"])
    batches: Dict[str, Dict[str, Any]] = {}
    if not table:
        return batches
    header = table[0]
    batch_ids = [clean(h) for h in header[1:4]]
    # normalize "Lot # AML-2026-01" -> "AML-2026-01"
    batch_ids = [b.replace("Lot # ", "") if b else b for b in batch_ids]
    for bid in batch_ids:
        batches[bid] = {}
    for row in rows_after_header(table):
        if not row or not row[0]:
            continue
        param = row[0]
        for idx, bid in enumerate(batch_ids):
            value = row[idx + 1] if idx + 1 < len(row) else None
            key = param.lower()
            if "yield" in key:
                nums = all_numbers(value)
                batches[bid]["batch_yield_kg"] = nums[0] if nums else None
                batches[bid]["batch_yield_pct"] = nums[1] if len(nums) > 1 else None
            elif "assay" in key:
                batches[bid]["assay_pct"] = first_number(value)
            elif "impurity a" in key:
                batches[bid]["impurity_a_pct"] = first_number(value)
            elif "impurity f" in key:
                batches[bid]["impurity_f_pct"] = first_number(value)
            elif "residual ipa" in key:
                batches[bid]["residual_ipa_ppm"] = first_number(value)
            elif "polymorphic" in key:
                batches[bid]["polymorphic_form"] = value
            elif "psd" in key:
                batches[bid]["psd_d50_um"] = first_number(value)
    return batches
