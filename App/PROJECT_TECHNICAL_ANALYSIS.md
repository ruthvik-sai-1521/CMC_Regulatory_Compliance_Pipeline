# CMC Regulatory Compliance Pipeline: Technical Analysis

## 1. Executive Summary

This project implements an end-to-end proof of concept for converting two pharmaceutical regulatory PDFs into structured Chemistry, Manufacturing, and Controls (CMC) data and auditing that data against configurable GxP rules.

The pipeline is built around four stages:

1. Extract tables from the CTD Module 3 dossier PDF.
2. Extract tables from the Site QA and batch audit PDF.
3. Merge both independent results into one `regulatoryFiling` object, matching commercial batches by batch ID.
4. Evaluate that object with rules loaded from `rules.yaml` and produce a structured compliance report with batch-level and dossier-level verdicts.

The bundled reference run is reproducible and produces:

- 3 commercial batches: `AML-2026-01`, `AML-2026-02`, and `AML-2026-03`
- Data completeness: `PASS`
- Rules evaluated: `46`
- Rule violations: `11`
- Severity totals: `5 CRITICAL`, `6 MAJOR`, `0 MINOR`
- Final verdict: `REJECTED_HOLD_SUBMISSION`

The result is appropriate for a technical demonstration and pre-filing review aid. It is not yet a production-grade validated GxP system because it does not currently validate the generated object against the JSON Schema, persist live output files, provide audit-trail logging, or use a document/OCR strategy for arbitrary PDF layouts.

## 2. Requirements Interpreted

The assignment contains two primary functional requirements and several reporting expectations.

### Part 1: Unstructured-to-structured parsing

- Ingest the FDA/CTD Module 3 dossier PDF.
- Ingest the Site QA, eBMR, CoA, deviation, and disposition PDF.
- Populate the target `regulatoryFiling.json` structure.
- Map nested content including:
  - document metadata
  - drug-substance profile and IUPAC nomenclature
  - KSMs and raw materials
  - critical process parameters and hold times
  - impurity and residual-solvent profiles
  - nitrosamine risk information and batch levels
  - elemental impurities
  - release specifications
  - analytical method validation
  - stability data
  - batch CoA results
  - process validation yields
  - eBMR process data
  - QA review, deviation, and disposition records

### Part 2: Automated compliance audit

- Load the populated filing and `rules.yaml`.
- Check mandatory sections for completeness.
- Evaluate configured CMC, CPP, nitrosamine, data-integrity, deviation, and disposition rules.
- Report each violation with rule ID, affected batch, parameter, actual value, expected value, and severity.
- Produce batch verdicts and a final `APPROVED_FOR_FILING` or `REJECTED_HOLD_SUBMISSION` verdict.

### Communication requirement

- Explain the requirements, implementation, architecture, data flow, logic, strategies, results, and remaining gaps in language suitable for a founder or technical stakeholder.

## 3. What Is Present in the Project

### Backend

- `backend/app/main.py`: FastAPI application, endpoints, temporary upload handling, and pipeline orchestration.
- `backend/app/parser/dossier_parser.py`: table-based extraction from the CTD dossier.
- `backend/app/parser/qa_parser.py`: table-based extraction from the QA package.
- `backend/app/parser/schema_mapper.py`: combines dossier and QA dictionaries into the target filing shape.
- `backend/app/parser/utils.py`: table discovery, whitespace cleanup, and numeric extraction helpers.
- `backend/app/rules/engine.py`: completeness checks, rule evaluation, violation construction, verdict roll-up, and report generation.
- `backend/regulatoryFiling.schema.json`: target JSON structure/template.
- `backend/rules.yaml`: configurable rules and verdict policy.
- `backend/sample_data/regulatoryFiling.json`: checked-in populated reference artifact.
- `backend/sample_data/compliance_report.json`: checked-in reference audit artifact.
- `backend/sample_inputs/`: bundled source PDFs used for the live sample run.

### Frontend and deployment

- `frontend/index.html` and `frontend/static/`: static dashboard served by FastAPI.
- `Dockerfile`: Python 3.11 container, dependency installation, backend/frontend copy, and Uvicorn startup.
- `railway.json`, `nixpacks.toml`, and `Procfile`: deployment/startup alternatives.

## 4. Architecture

```text
                    +----------------------------+
                    | CTD Module 3 dossier PDF   |
                    +-------------+--------------+
                                  |
                                  v
                    +----------------------------+
                    | dossier_parser.py           |
                    | metadata, CMC, batch data   |
                    +-------------+--------------+
                                  |
                                  | dossier dictionary
                                  v
+------------------+    +---------+------------------+    +------------------+
| QA package PDF   | -> | schema_mapper.py           | -> | regulatoryFiling |
| eBMR, CoA, QA    |    | batch merge/cross-reference|    | structured JSON  |
+------------------+    +---------+------------------+    +---------+--------+
          |                         ^                          |
          v                         |                          v
 +-------------------+              |                +-----------------------+
 | qa_parser.py      |--------------+                | rules/engine.py       |
 | QA dictionaries   |                               | completeness + audit |
 +-------------------+                               +-----------+-----------+
                                                                    |
                                                                    v
                                                     +-----------------------+
                                                     | compliance_report      |
                                                     | violations + verdict  |
                                                     +-----------------------+
```

The HTTP layer exposes this architecture through FastAPI:

- `GET /api/sample/run`: executes the complete bundled pipeline.
- `POST /api/pipeline/run`: accepts two uploaded PDFs and returns both artifacts in one response.
- `POST /api/audit`: audits an already-populated filing without parsing PDFs.
- `GET /api/sample/filing` and `GET /api/sample/report`: return checked-in reference artifacts.
- `GET /api/schema` and `GET /api/rules`: expose the active contract and rule configuration.
- `GET /api/health`: reports service and configuration availability.

## 5. End-to-end Data Flow

1. The caller supplies two PDFs, or the API selects the bundled sample PDFs.
2. Uploaded files are copied to a UUID-named temporary directory.
3. `pdfplumber` extracts tables page by page.
4. The parsers locate tables by matching header keywords rather than fixed page numbers. This tolerates page movement when a document is re-paginated, provided the table layout and header wording remain compatible.
5. Dossier fields are extracted into sections such as metadata, nomenclature, KSMs, process controls, impurities, release specifications, and stability.
6. QA fields are extracted into eBMR, CoA, nitrosamine, process-yield, deviation, and disposition structures.
7. `schema_mapper.py` takes the union of batch IDs found across dossier and QA sources. For each batch it creates separate `dossier_reported`, `ebmr_process_data`, `coa_results`, `nitrosamine_levels`, and `process_validation_yields` objects.
8. The mapper adds site, market, and QA protocol metadata and assembles the complete filing dictionary.
9. `rules.yaml` is loaded with `yaml.safe_load`.
10. The rule engine checks mandatory paths, then evaluates batch rules, deviation rules, and disposition rules.
11. Violations are aggregated by severity and batch. Any failed completeness check, CRITICAL violation, or MAJOR violation rejects/holds the dossier. Otherwise it is approved.
12. The API returns `{ regulatoryFiling, compliance_report }`. Temporary uploads are deleted in a `finally` block.

## 6. Parsing Strategies and Logic

### Table discovery

`find_table()` scans all extracted tables and searches the first row for required header keywords. Examples include `submitting entity`, `specification / empirical value`, `batch 01 result`, `record id`, and `disposition decision`.

This is better than hardcoding page numbers, but it is still layout-dependent. A scanned PDF, changed header text, merged cells, or materially different column ordering can cause an empty section or a shifted value.

### Numeric extraction

`first_number()` and `all_numbers()` use regular expressions to extract numeric values from cells such as `97.1%`, `58.9%`, or `450 - 820 ppm`. This makes rule comparisons straightforward, but units and semantic meaning are not independently modeled. The parser assumes the source cell order and unit are known.

### Source separation and cross-document integrity

The dossier and QA package are intentionally parsed independently. The mapper preserves the dossier's self-reported assay separately from the QA CoA assay. `RULE-INTEGRITY-001` then checks the absolute difference against a `0.5%` tolerance. This is an important design choice because a dossier-only parser could miss a conflict between submitted and independently audited values.

### Missing data behavior

Missing numeric values are skipped by numeric rules rather than reported as rule failures. Missing mandatory sections are reported by the completeness gate. This means an individual missing batch parameter can escape a numeric violation unless its containing section is also considered incomplete.

## 7. Rule Engine Behavior

The active configuration contains:

- 11 mandatory section paths.
- 12 batch rules covering assay, impurities, solvent, water, process yields, CPPs, nitrosamines, and dossier/CoA consistency.
- 2 deviation rules for open critical/major records.
- 1 disposition rule for reject/hold decisions.
- A verdict policy naming approved and rejected verdict strings.

The reference failure is centered on `AML-2026-02`:

- QA CoA assay is `97.1%`, below the `98.0%` minimum.
- CoA Impurity A is `0.28%`, above the `0.10%` limit.
- Overall process yield is `58.9%`, below the `75.0%` minimum.
- Step 2 yield is `74.1%`, below the `90.0%` minimum.
- Step 2 deprotection time is `8.5 hours`, above the `6.0 hour` limit.
- Dossier assay is `99.6%` versus QA CoA `97.1%`, a `2.5%` discrepancy.
- Two critical deviation records remain open or under investigation.
- One major deviation remains open.
- QA records `REJECT Batch AML-2026-02` and `HOLD Regulatory Filing`.

`AML-2026-01` and `AML-2026-03` have no configured critical or major violations in the reference run. The dossier-level verdict is nevertheless rejected because the policy is conservative: one failed mandatory section or any critical/major violation is sufficient to hold submission.

## 8. Requirement-by-Requirement Status

| Requirement | Status | Evidence / qualification |
|---|---|---|
| Ingest both PDFs | Satisfied for supplied layout | `parse_dossier()` and `parse_qa_package()` use `pdfplumber`; bundled live run succeeds. |
| Extract CMC and QA data | Satisfied for supplied layout | Parsers cover the requested metadata, CMC, batch, CoA, eBMR, deviation, and disposition areas. |
| Populate target filing structure | Mostly satisfied | `schema_mapper.py` constructs the target shape and a populated reference JSON exists. |
| Write populated `regulatoryFiling.json` during a run | Not satisfied | Runtime returns an in-memory object; it does not write a new JSON file. The checked-in sample is a pre-generated artifact. |
| Validate against JSON Schema | Not satisfied | The schema is exposed and documented, but no `jsonschema` dependency or validation call is present. |
| Load and execute YAML rules | Satisfied | `load_rules_yaml()` and the rule engine execute the configured rule groups. |
| Completeness PASS/FAIL | Satisfied | Mandatory paths are checked for non-null and non-empty values. |
| Detailed violations | Satisfied | Reports include rule ID, batch, parameter, actual, expected, severity, category, and description. |
| Final approved/rejected verdict | Satisfied | The two requested verdict strings are produced. |
| Persist `compliance_report.json` during a run | Not satisfied | Runtime returns JSON; it does not persist a newly generated report file. |
| Founder-level explanation | Added | This file documents the architecture, data flow, logic, result, status, and gaps. |

## 9. How to Explain It to a Founder

“We built a two-document regulatory intelligence pipeline. It reads the formal CTD dossier and independently reads the site's QA evidence. It converts both into a common filing record, keeps source values separate, and compares them batch by batch. Then a configurable rule engine checks release specifications, impurities, solvents, process yields, critical process parameters, nitrosamines, deviations, and QA disposition. The important business value is that it can detect both ordinary specification failures and data-integrity mismatches between what the dossier says and what QA measured.”

“For the supplied Amlodipine package, the system reaches the correct conservative outcome: hold the filing. It identifies that Batch AML-2026-02 has an out-of-specification assay, elevated Impurity A, poor process yields, an extended deprotection time, unresolved deviations, a dossier/CoA assay mismatch, and explicit reject/hold decisions. The other two batches pass the configured batch rules, but the overall submission remains rejected because the dossier contains a material failed batch and unresolved critical/major QA findings.”

“The current version is a working demonstrator and integration foundation. Before production use in a regulated environment, we need schema validation, stronger document extraction and confidence handling, immutable audit logs, authenticated access, rule/version traceability, automated tests, and formal validation of the intended use.”

## 10. Technical Gaps and Recommended Next Steps

1. Add `jsonschema` validation after mapping and before auditing. Return a clear validation error when required types, enums, or nested properties do not conform.
2. Add an explicit artifact writer so a pipeline run can optionally save `regulatoryFiling.json` and `compliance_report.json` with a run ID and source-document hashes.
3. Add parser tests using the supplied PDFs and fixture tables. Include missing-table, reordered-column, malformed-number, and scanned-PDF cases.
4. Add a parser confidence/completeness model. Distinguish “not found,” “not applicable,” and “found but unparsable” instead of silently producing `None`.
5. Replace hard-coded batch IDs in QA parser defaults with IDs discovered from the table headers, while retaining strict validation of expected batch identity.
6. Make the configured `verdict_policy.auto_reject_severities` and `hold_review_severities` drive verdict logic. The current engine effectively hardcodes CRITICAL and MAJOR handling.
7. Fix policy/report semantics for filing-wide disposition findings. A disposition such as `HOLD Regulatory Filing` is currently represented with `ALL BATCHES / FILING`, while batch roll-up only associates violations whose `affected_batch` exactly matches a batch ID.
8. Add structured application logging, correlation IDs, source hashes, rule-set version, parser version, and operator identity for auditability.
9. Add security controls before external deployment: authentication, authorization, upload size/type limits, malware scanning, rate limiting, and restricted CORS rather than `allow_origins=["*"]`.
10. Establish regulated-system controls separately from code: approved validation protocol, change control, electronic records/signature assessment, backup/retention policy, and QA ownership of rule configuration.

## 11. How to Run and Demonstrate

From the project root:

```powershell
docker build -t cmc-pipeline .
docker run --name cmc-regulens -p 8001:8000 cmc-pipeline
```

Then open `http://localhost:8001` for the dashboard or use:

```text
GET  /api/health
GET  /api/sample/run
GET  /api/sample/filing
GET  /api/sample/report
POST /api/pipeline/run
POST /api/audit
```

For a direct Python smoke test from the project root:

```powershell
python -c "import sys; sys.path.insert(0, 'backend'); from app.parser import parse_dossier, parse_qa_package, build_regulatory_filing; from app.rules.engine import load_rules_yaml, run_compliance_audit; d=parse_dossier('backend/sample_inputs/Amlodipine_Besylate_14Page_FDA_Dossier.pdf'); q=parse_qa_package('backend/sample_inputs/Amlodipine_Besylate_QA_Compliance_Package.pdf'); f=build_regulatory_filing(d,q); r=run_compliance_audit(f,load_rules_yaml('backend/rules.yaml')); print(r['final_dossier_verdict'])"
```

The expected final output for the bundled sample is `REJECTED_HOLD_SUBMISSION`.

## 12. Final Assessment

The project satisfies the core proof-of-concept objective and demonstrates the complete intended pipeline on the supplied PDFs. The parser, mapper, rule engine, API, dashboard, Docker packaging, sample filing, and sample audit report are all present and the live sample run is reproducible.

The requirements that are only partially met are file persistence and strict schema conformance: the runtime creates Python dictionaries and returns them as JSON, but it does not write or validate the named JSON artifacts during each execution. Those are straightforward next implementation steps. The larger production risks are extraction robustness, traceability, security, and formal GxP validation rather than the basic pipeline architecture.