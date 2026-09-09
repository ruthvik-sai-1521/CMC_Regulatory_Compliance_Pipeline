"""
Central configuration for the Regulatory CMC Compliance Pipeline.

All paths are resolved relative to the `backend/` directory so the service
runs identically on a local machine, inside Docker, and on Railway.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend

RULES_YAML_PATH = Path(os.getenv("RULES_YAML_PATH", BASE_DIR / "rules.yaml"))
SCHEMA_TEMPLATE_PATH = Path(os.getenv("SCHEMA_TEMPLATE_PATH", BASE_DIR / "regulatoryFiling.schema.json"))

SAMPLE_DATA_DIR = BASE_DIR / "sample_data"
SAMPLE_INPUTS_DIR = BASE_DIR / "sample_inputs"

SAMPLE_POPULATED_JSON = SAMPLE_DATA_DIR / "regulatoryFiling.json"
SAMPLE_COMPLIANCE_REPORT = SAMPLE_DATA_DIR / "compliance_report.json"

SAMPLE_DOSSIER_PDF = SAMPLE_INPUTS_DIR / "Amlodipine_Besylate_14Page_FDA_Dossier.pdf"
SAMPLE_QA_PDF = SAMPLE_INPUTS_DIR / "Amlodipine_Besylate_QA_Compliance_Package.pdf"

# Runtime workspace for uploaded files / generated artifacts (ephemeral on Railway,
# which is fine -- every request is self-contained and returns its own JSON payloads).
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR", "/tmp/cmc_pipeline"))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = BASE_DIR.parent / "frontend"

APP_VERSION = "1.0.0"
