import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import ValidationError, validate

from . import config
from .parser import build_regulatory_filing, parse_dossier, parse_qa_package
from .rules.engine import load_rules_yaml, run_compliance_audit

app = FastAPI(
    title="CMC Regulatory Compliance Pipeline",
    description=(
        "Parses unstructured pharmaceutical regulatory PDFs (ICH CTD Module 3.2.S dossiers "
        "and Site QA compliance packages) into structured CMC data, then runs an automated "
        "GxP rule engine to produce a compliance audit report and filing verdict."
    ),
    version=config.APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Health / metadata
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "cmc-compliance-pipeline",
        "version": config.APP_VERSION,
        "rules_file_found": config.RULES_YAML_PATH.exists(),
        "schema_file_found": config.SCHEMA_TEMPLATE_PATH.exists(),
    }


@app.get("/api/schema")
def get_schema():
    """Returns the JSON Schema used to validate generated filings."""
    if not config.SCHEMA_TEMPLATE_PATH.exists():
        raise HTTPException(404, "Schema template not found on server.")
    return json.loads(config.SCHEMA_TEMPLATE_PATH.read_text())


@app.get("/api/rules")
def get_rules():
    """Returns the active rules.yaml configuration as JSON, for UI display."""
    if not config.RULES_YAML_PATH.exists():
        raise HTTPException(404, "rules.yaml not found on server.")
    return load_rules_yaml(str(config.RULES_YAML_PATH))


# --------------------------------------------------------------------------
# Sample data (pre-computed from the reference Amlodipine Besylate package,
# so the reviewer gets an instant, no-upload-required demo)
# --------------------------------------------------------------------------
@app.get("/api/sample/filing")
def sample_filing():
    if not config.SAMPLE_POPULATED_JSON.exists():
        raise HTTPException(404, "Sample regulatoryFiling.json has not been generated yet.")
    return json.loads(config.SAMPLE_POPULATED_JSON.read_text())


@app.get("/api/sample/report")
def sample_report():
    if not config.SAMPLE_COMPLIANCE_REPORT.exists():
        raise HTTPException(404, "Sample compliance_report.json has not been generated yet.")
    return json.loads(config.SAMPLE_COMPLIANCE_REPORT.read_text())


@app.get("/api/sample/run")
def sample_run():
    """Runs the full live pipeline against the bundled sample PDFs (Part 1 + Part 2)."""
    return _run_pipeline(str(config.SAMPLE_DOSSIER_PDF), str(config.SAMPLE_QA_PDF))


# --------------------------------------------------------------------------
# Part 1 + Part 2: full pipeline on uploaded files
# --------------------------------------------------------------------------
@app.post("/api/pipeline/run")
async def run_pipeline(
    dossier_pdf: Optional[UploadFile] = File(None, description="ICH CTD Module 3.2.S regulatory dossier PDF"),
    qa_pdf: Optional[UploadFile] = File(None, description="Site QA & Batch Audit Record PDF"),
):
    """
    Accepts the two source PDFs, runs Part 1 (unstructured -> structured
    parsing into regulatoryFiling.json) and Part 2 (rule-engine GxP audit),
    and returns both artifacts in a single response.

    If a file is omitted, the corresponding bundled sample PDF is used, so
    the endpoint can also be used to explore/replace a single document.
    """
    work_dir = config.RUNTIME_DIR / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        dossier_path = str(config.SAMPLE_DOSSIER_PDF)
        qa_path = str(config.SAMPLE_QA_PDF)

        if dossier_pdf is not None:
            dossier_path = str(work_dir / "dossier.pdf")
            _save_upload(dossier_pdf, dossier_path)

        if qa_pdf is not None:
            qa_path = str(work_dir / "qa.pdf")
            _save_upload(qa_pdf, qa_path)

        return _run_pipeline(dossier_path, qa_path)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/api/audit")
async def audit_only(filing: dict):
    """
    Part 2 as a standalone endpoint: accepts an already-populated
    regulatoryFiling.json body and runs the GxP rule engine against it.
    """
    try:
        _validate_filing(filing)
    except ValidationError as exc:
        raise HTTPException(422, f"Filing failed schema validation: {exc.message}") from exc
    _write_artifact(config.POPULATED_JSON_PATH, filing)
    rules_config = load_rules_yaml(str(config.RULES_YAML_PATH))
    report = run_compliance_audit(filing, rules_config)
    _write_artifact(config.COMPLIANCE_REPORT_PATH, report)
    return report


def _run_pipeline(dossier_path: str, qa_path: str):
    try:
        dossier_data = parse_dossier(dossier_path)
        qa_data = parse_qa_package(qa_path)
        filing = build_regulatory_filing(dossier_data, qa_data)
        _validate_filing(filing)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ValidationError):
            raise HTTPException(422, f"Generated filing failed schema validation: {exc.message}") from exc
        raise HTTPException(422, f"Failed to parse source PDF(s): {exc}") from exc

    rules_config = load_rules_yaml(str(config.RULES_YAML_PATH))
    report = run_compliance_audit(filing, rules_config)
    _write_artifact(config.POPULATED_JSON_PATH, filing)
    _write_artifact(config.COMPLIANCE_REPORT_PATH, report)

    return {
        "regulatoryFiling": filing,
        "compliance_report": report,
        "artifacts": {
            "regulatoryFiling": str(config.POPULATED_JSON_PATH),
            "compliance_report": str(config.COMPLIANCE_REPORT_PATH),
        },
    }


def _validate_filing(filing: dict):
    with open(config.SCHEMA_TEMPLATE_PATH, "r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    validate(instance=filing, schema=schema)


def _write_artifact(path: Path, payload: dict):
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def _save_upload(upload: UploadFile, dest_path: str):
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(upload.file, f)


# --------------------------------------------------------------------------
# Frontend (single-page dashboard) -- mounted last so /api/* routes win
# --------------------------------------------------------------------------
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
