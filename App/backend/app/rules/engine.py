"""
Automated Rule Engine (Part 2 of the pipeline).

Loads a populated regulatoryFiling.json document plus a rules.yaml GxP
configuration, evaluates every configured rule, and returns a structured
compliance_report.json payload:

    {
      "data_completeness": {...},
      "rule_violations": [...],
      "rules_evaluated": N,
      "violations_by_severity": {...},
      "batch_verdicts": {...},
      "final_verdict": "APPROVED_FOR_FILING" | "REJECTED_HOLD_SUBMISSION",
      "generated_at": "..."
    }
"""
import datetime
from typing import Any, Dict, List

import yaml


def _get_path(obj: Any, path: str, default=None):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            return default
        if cur is None:
            return default
    return cur


def _section_present(filing: Dict[str, Any], path: str) -> bool:
    value = _get_path(filing, path, None)
    if value is None:
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True


def _check_completeness(filing: Dict[str, Any], mandatory_sections: List[str]) -> Dict[str, Any]:
    missing = [s for s in mandatory_sections if not _section_present(filing, s)]
    return {
        "status": "PASS" if not missing else "FAIL",
        "mandatory_sections_checked": mandatory_sections,
        "missing_sections": missing,
    }


def _evaluate_operator(value, operator: str, rule: Dict[str, Any]) -> bool:
    """Returns True if the value PASSES (i.e. no violation)."""
    if value is None:
        # Missing data is treated as a completeness gap, not evaluated numerically.
        return True
    if operator == "between":
        return rule["min"] <= value <= rule["max"]
    if operator == "max":
        return value <= rule["max"]
    if operator == "min":
        return value >= rule["min"]
    return True


def _run_batch_rules(filing: Dict[str, Any], batch_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    violations = []
    for batch in filing.get("commercial_batches", []):
        batch_id = batch.get("batch_id")
        for rule in batch_rules:
            if rule.get("type") == "cross_field_consistency":
                a = _get_path(batch, rule["field_a"])
                b = _get_path(batch, rule["field_b"])
                if a is None or b is None:
                    continue
                if abs(a - b) > rule["tolerance"]:
                    violations.append({
                        "rule_id": rule["id"],
                        "category": rule["category"],
                        "description": rule["description"],
                        "affected_batch": batch_id,
                        "parameter": f"{rule['field_a']} vs {rule['field_b']}",
                        "actual_value": f"dossier={a} / QA CoA={b} (Δ={round(abs(a - b), 3)})",
                        "expected": f"within ±{rule['tolerance']}",
                        "severity": rule["severity"],
                    })
                continue

            value = _get_path(batch, rule["field"])
            passed = _evaluate_operator(value, rule["operator"], rule)
            if not passed:
                if rule["operator"] == "between":
                    expected = f"{rule['min']} - {rule['max']}"
                elif rule["operator"] == "max":
                    expected = f"<= {rule['max']}"
                else:
                    expected = f">= {rule['min']}"
                violations.append({
                    "rule_id": rule["id"],
                    "category": rule["category"],
                    "description": rule["description"],
                    "affected_batch": batch_id,
                    "parameter": rule["field"],
                    "actual_value": value,
                    "expected": expected,
                    "severity": rule["severity"],
                })
    return violations


def _run_deviation_rules(filing: Dict[str, Any], deviation_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    violations = []
    deviations = filing.get("qa_compliance", {}).get("deviations", [])
    for rule in deviation_rules:
        for dev in deviations:
            severity_match = dev.get("severity", "").upper() in [s.upper() for s in rule["match_severity"]]
            status_forbidden = dev.get("status", "").upper() in [s.upper() for s in rule["forbidden_status"]]
            if severity_match and status_forbidden:
                violations.append({
                    "rule_id": rule["id"],
                    "category": rule["category"],
                    "description": rule["description"],
                    "affected_batch": dev.get("affected_batch"),
                    "parameter": dev.get("record_id"),
                    "actual_value": f"{dev.get('event_description')} [{dev.get('status')}]",
                    "expected": f"no {'/'.join(rule['forbidden_status'])} record at {'/'.join(rule['match_severity'])} severity",
                    "severity": rule["severity"],
                })
    return violations


def _run_disposition_rules(filing: Dict[str, Any], disposition_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    violations = []
    signoffs = filing.get("qa_compliance", {}).get("disposition_signoff", [])
    batch_ids = [b.get("batch_id") for b in filing.get("commercial_batches", [])]
    for rule in disposition_rules:
        for entry in signoffs:
            decision = (entry.get("disposition_decision") or "").upper()
            if any(kw in decision for kw in rule["forbidden_keywords"]):
                affected = next((bid for bid in batch_ids if bid and bid in decision), None) or "ALL BATCHES / FILING"
                violations.append({
                    "rule_id": rule["id"],
                    "category": rule["category"],
                    "description": rule["description"],
                    "affected_batch": affected,
                    "parameter": entry.get("qa_function"),
                    "actual_value": entry.get("disposition_decision"),
                    "expected": f"decision must not contain {' / '.join(rule['forbidden_keywords'])}",
                    "severity": rule["severity"],
                })
    return violations


def run_compliance_audit(filing: Dict[str, Any], rules_config: Dict[str, Any]) -> Dict[str, Any]:
    mandatory_sections = rules_config.get("mandatory_sections", [])
    completeness = _check_completeness(filing, mandatory_sections)

    violations = []
    violations += _run_batch_rules(filing, rules_config.get("batch_rules", []))
    violations += _run_deviation_rules(filing, rules_config.get("deviation_rules", []))
    violations += _run_disposition_rules(filing, rules_config.get("disposition_rules", []))

    total_rules = (
        len(filing.get("commercial_batches", [])) * len(rules_config.get("batch_rules", []))
        + len(rules_config.get("deviation_rules", [])) * len(filing.get("qa_compliance", {}).get("deviations", []))
        + len(rules_config.get("disposition_rules", [])) * len(filing.get("qa_compliance", {}).get("disposition_signoff", []))
    )

    by_severity = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0}
    for v in violations:
        by_severity[v["severity"]] = by_severity.get(v["severity"], 0) + 1

    # Per-batch verdict roll-up
    batch_verdicts = {}
    for batch in filing.get("commercial_batches", []):
        bid = batch.get("batch_id")
        batch_violations = [v for v in violations if v["affected_batch"] == bid]
        critical = [v for v in batch_violations if v["severity"] == "CRITICAL"]
        major = [v for v in batch_violations if v["severity"] == "MAJOR"]
        if critical:
            verdict = "REJECTED_HOLD_SUBMISSION"
        elif major:
            verdict = "REJECTED_HOLD_SUBMISSION"
        else:
            verdict = "APPROVED_FOR_FILING"
        batch_verdicts[bid] = {
            "verdict": verdict,
            "critical_count": len(critical),
            "major_count": len(major),
            "minor_count": len([v for v in batch_violations if v["severity"] == "MINOR"]),
            "total_violations": len(batch_violations),
        }

    policy = rules_config.get("verdict_policy", {})
    approved_verdict = policy.get("approved_verdict", "APPROVED_FOR_FILING")
    rejected_verdict = policy.get("rejected_verdict", "REJECTED_HOLD_SUBMISSION")

    if completeness["status"] == "FAIL":
        final_verdict = rejected_verdict
        verdict_reason = "Mandatory CTD/QA sections missing from the structured filing."
    elif by_severity.get("CRITICAL", 0) > 0:
        final_verdict = rejected_verdict
        verdict_reason = f"{by_severity['CRITICAL']} CRITICAL severity rule violation(s) identified."
    elif by_severity.get("MAJOR", 0) > 0:
        final_verdict = rejected_verdict
        verdict_reason = f"{by_severity['MAJOR']} MAJOR severity rule violation(s) identified."
    else:
        final_verdict = approved_verdict
        verdict_reason = "No CRITICAL or MAJOR severity violations identified; all mandatory sections present."

    report = {
        "report_id": f"AUDIT-{filing.get('document_metadata', {}).get('document_id', 'UNKNOWN')}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "data_completeness": completeness,
        "rules_evaluated": total_rules,
        "rule_violations": violations,
        "violations_by_severity": by_severity,
        "batch_verdicts": batch_verdicts,
        "final_dossier_verdict": final_verdict,
        "verdict_reason": verdict_reason,
    }
    return report


def load_rules_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
