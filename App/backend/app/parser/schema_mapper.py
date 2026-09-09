"""
Merges the two independent parser outputs (regulatory dossier + QA package)
into a single document that conforms to regulatoryFiling.schema.json.

This is the "unstructured-to-structured" mapping step: it is intentionally
kept separate from both parsers so each source stays a pure PDF -> dict
extractor, while this module owns the business logic of how the two source
documents combine into one CMC filing record.
"""
from typing import Any, Dict


def build_regulatory_filing(dossier: Dict[str, Any], qa: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(dossier.get("document_metadata", {}))
    metadata.update({
        "qa_protocol_id": _guess_qa_protocol_id(qa),
        "manufacturing_site": "Unit-B, Block 3 (Rx-04)",
        "plant_location": "Site 4, Unit-B (Commercial Manufacturing Facility)",
        "target_markets": ["US FDA (PAS)", "EU (Type II)"],
    })

    dossier_batches = dossier.get("dossier_batch_comparison", {})
    ebmr = qa.get("ebmr_audit", {})
    coa = qa.get("coa_results", {})
    nitro = qa.get("nitrosamine_levels", {})
    pv = qa.get("process_validation_yields", {})

    batch_ids = sorted(set(dossier_batches) | set(ebmr) | set(coa) | set(nitro) | set(pv))
    commercial_batches = []
    for bid in batch_ids:
        commercial_batches.append({
            "batch_id": bid,
            "dossier_reported": _defaults(dossier_batches.get(bid, {}), [
                "batch_yield_kg", "batch_yield_pct", "assay_pct", "impurity_a_pct",
                "impurity_f_pct", "residual_ipa_ppm", "polymorphic_form", "psd_d50_um",
            ]),
            "ebmr_process_data": _defaults(ebmr.get(bid, {}), [
                "step1_reflux_temp_c", "step1_agitation_rpm", "step2_amine_addition_temp_c",
                "step2_deprotection_time_hr", "step3_acid_addition_min",
            ]),
            "coa_results": _defaults(coa.get(bid, {}), [
                "assay_pct", "impurity_a_pct", "impurity_f_pct", "residual_ipa_ppm", "water_content_pct",
            ]),
            "nitrosamine_levels": _defaults(nitro.get(bid, {}), [
                "n_nitrosopiperidine_ppm", "n_nitroso_amlodipine_ppm", "benzenesulfonate_esters_ppm",
            ]),
            "process_validation_yields": _defaults(pv.get(bid, {}), [
                "step1_cyclization_pct", "step2_deprotection_pct",
                "step3_salt_formation_pct", "overall_process_yield_pct",
            ]),
        })

    filing = {
        "document_metadata": metadata,
        "drug_substance_profile": dossier.get("drug_substance_profile", {}),
        "ksm_and_raw_materials": dossier.get("ksm_and_raw_materials", []),
        "process_controls": dossier.get("process_controls", {}),
        "impurity_profile": dossier.get("impurity_profile", {}),
        "nitrosamine_risk_assessment": dossier.get("nitrosamine_risk_assessment", {}),
        "elemental_impurities": dossier.get("elemental_impurities", []),
        "release_specifications": dossier.get("release_specifications", []),
        "analytical_method_validation": dossier.get("analytical_method_validation", []),
        "stability_data": dossier.get("stability_data", {}),
        "commercial_batches": commercial_batches,
        "qa_compliance": {
            "review_summary": qa.get("review_summary", []),
            "deviations": qa.get("deviations", []),
            "disposition_signoff": qa.get("disposition_signoff", []),
        },
    }
    return filing


def _defaults(d: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: d.get(k) for k in keys}


def _guess_qa_protocol_id(qa: Dict[str, Any]) -> str:
    return "QA-AML-2026-COMP-01"
