# CMC Regulatory Compliance Pipeline
### Amlodipine Besylate API — Unstructured Dossier Parsing + Automated GxP Rule Engine

An end-to-end pipeline that ingests unstructured pharmaceutical regulatory PDFs (an ICH CTD
Module 3.2.S dossier and a Site QA compliance package), extracts structured CMC data into
`regulatoryFiling.json`, and runs a configurable GxP rule engine (`rules.yaml`) to produce a
`compliance_report.json` audit with a final filing verdict.

```
APPROVED_FOR_FILING   or   REJECTED_HOLD_SUBMISSION
```

---

## 1. What's inside

```
App/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app (REST API + serves the frontend)
│   │   ├── config.py            Path/env configuration
│   │   ├── parser/
│   │   │   ├── dossier_parser.py   Extracts CMC data from the CTD Module 3 PDF
│   │   │   ├── qa_parser.py        Extracts eBMR / CoA / deviation data from the QA PDF
│   │   │   ├── schema_mapper.py    Merges both sources into the regulatoryFiling schema
│   │   │   └── utils.py            Shared table/number-parsing helpers
│   │   └── rules/
│   │       └── engine.py           Loads rules.yaml, evaluates it, builds the audit report
│   ├── regulatoryFiling.schema.json   Blank target JSON schema (Part 1 deliverable template)
│   ├── rules.yaml                     GxP rule configuration (Part 2 deliverable template)
│   ├── sample_data/
│   │   ├── regulatoryFiling.json      Pre-generated Part 1 output (reference run)
│   │   └── compliance_report.json     Pre-generated Part 2 output (reference run)
│   ├── sample_inputs/                 The two source PDFs, bundled for the one-click demo
│   └── requirements.txt
├── frontend/                    Static single-page dashboard (no build step required)
│   ├── index.html
│   └── static/{css,js}/
├── Dockerfile                   Production image (used by Railway)
├── railway.json                 Railway build/deploy config (Dockerfile builder)
├── nixpacks.toml                Fallback build path if you switch Railway to Nixpacks
├── Procfile                     Fallback process definition (Heroku-style / Nixpacks)
└── .env.example
```

**Why this structure?** The parser is split into three single-purpose modules
(`dossier_parser.py`, `qa_parser.py`, `schema_mapper.py`) instead of one monolithic script, so
each source document stays a pure "PDF → dict" extractor and the business logic of *how the two
documents combine* (batch matching, dossier-vs-QA cross-referencing) lives in one clearly owned
place. The rule engine is fully data-driven from `rules.yaml` — adding, removing, or re-tuning a
GxP rule never requires touching Python code.

---

## 2. How the parsing actually works (Part 1)

Both source PDFs are "unstructured" only in the sense that they are free-form regulatory
documents — the individual data tables inside them are consistently formatted. Rather than
hardcoding page numbers (which breaks the moment a dossier is re-paginated), every table is
located dynamically at parse time by matching its header row against a known signature
(`find_table()` in `app/parser/utils.py`), then mapped into the schema.

The two documents are cross-referenced batch-by-batch (`AML-2026-01/02/03`):

| Source | What it contributes per batch |
|---|---|
| Regulatory Dossier (Module 3, page 14) | `dossier_reported` — the dossier's own self-reported release data |
| QA Package — eBMR audit table | `ebmr_process_data` — actual executed process parameters |
| QA Package — finished-product CoA table | `coa_results` — independently audited lab results |
| QA Package — nitrosamine trending table | `nitrosamine_levels` |
| QA Package — process validation table | `process_validation_yields` |
| QA Package — deviation/CAPA log & disposition sign-off | `qa_compliance.deviations` / `disposition_signoff` |

This separation is deliberate: in the reference package, the dossier's self-reported Batch
AML-2026-02 assay (99.6%) does **not** match the independently audited QA CoA result (97.1%) —
a real data-integrity red flag. `RULE-INTEGRITY-001` in `rules.yaml` catches exactly this kind
of discrepancy, which a pipeline that only reads the dossier would miss entirely.

## 3. How the rule engine works (Part 2)

`rules.yaml` defines:
- **`mandatory_sections`** — a completeness gate checked before any rule runs.
- **`batch_rules`** — numeric/range/consistency checks evaluated once per commercial batch
  (assay range, impurity limits, residual solvent limits, CPP/PAR compliance, nitrosamine
  limits, and the dossier-vs-QA consistency check).
- **`deviation_rules`** — scans the QA deviation/CAPA log for CRITICAL/MAJOR records that are
  still open at filing time.
- **`disposition_rules`** — scans the QA sign-off block for any REJECT/HOLD decision.
- **`verdict_policy`** — any CRITICAL violation, any MAJOR violation, or a failed completeness
  check triggers `REJECTED_HOLD_SUBMISSION`; otherwise `APPROVED_FOR_FILING`.

Every violation object in `compliance_report.json` includes `rule_id`, `affected_batch`,
`parameter`, `actual_value`, `expected`, `severity`, and `category` — everything needed to
route it straight to a QA reviewer.

Because the engine is generic (`app/rules/engine.py` never mentions "Amlodipine" or any batch
ID), the same pipeline works unmodified for a different API's dossier/QA pair as long as the
populated JSON follows the same schema — just point it at a different `rules.yaml`.

---

## 4. Run it locally

**Requirements:** Python 3.11+

```bash
cd App/backend
python -m venv .venv      
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the dashboard is served directly by the API (no separate
frontend server needed). Click **"Run With Bundled Sample Package"** for an instant demo, or
drop in your own two PDFs and click **"Run Pipeline On Uploaded Files"**.

Interactive API docs: **http://localhost:8000/docs**

### Run without the UI (pure Python)

```python
from app.parser import parse_and_map
from app.rules.engine import load_rules_yaml, run_compliance_audit

filing = parse_and_map("sample_inputs/Amlodipine_Besylate_14Page_FDA_Dossier.pdf",
                        "sample_inputs/Amlodipine_Besylate_QA_Compliance_Package.pdf")
report = run_compliance_audit(filing, load_rules_yaml("rules.yaml"))
print(report["final_dossier_verdict"])
```

---

## 5. Run it with Docker

```bash
cd App
docker build -t cmc-pipeline .
docker run -p 8000:8000 cmc-pipeline
```

Open **http://localhost:8000**.

---

## 6. Deploy to Railway — what you need to do

The repo is Railway-ready out of the box (`Dockerfile` + `railway.json`, with `nixpacks.toml` /
`Procfile` as a fallback path). You still need to do the following yourself, since these are
account-specific actions I can't perform for you:

1. **Push this project to a GitHub repo** (Railway deploys from Git).
2. **In Railway:** *New Project → Deploy from GitHub repo* → select the repo.
3. Railway will detect the root `Dockerfile` automatically (builder is pinned to `DOCKERFILE`
   in `railway.json`). No build command needed.
4. **No environment variables are required to boot** — everything has a safe default in
   `app/config.py`. Railway automatically injects `$PORT`, which the Dockerfile's `CMD` and
   `railway.json`'s `startCommand` both already read (`--port ${PORT:-8000}`).
5. Once deployed, Railway gives you a public URL (`Settings → Networking → Generate Domain`).
   Open it — the dashboard loads at the root URL, exactly like local.
6. **Health check:** Railway is configured (`railway.json`) to poll `/api/health` — no action
   needed, but if your deploy is marked unhealthy, check that path first.
7. *(Optional)* If you'd rather not use the Dockerfile, delete/rename it and Railway will fall
   back to **Nixpacks** using `nixpacks.toml`, which installs `backend/requirements.txt` and
   runs the same `uvicorn` start command.

**Note on uploads:** uploaded PDFs are processed in a temporary directory (`/tmp/cmc_pipeline`)
and deleted immediately after each request — there is no persistent storage requirement, so the
service works statelessly on Railway's ephemeral filesystem with zero extra configuration.

---

## 7. API reference

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness/readiness check |
| GET | `/api/schema` | The blank target `regulatoryFiling.schema.json` |
| GET | `/api/rules` | The active `rules.yaml`, as JSON |
| GET | `/api/sample/run` | Runs the **full live pipeline** on the bundled sample PDFs |
| GET | `/api/sample/filing` | Pre-generated sample `regulatoryFiling.json` |
| GET | `/api/sample/report` | Pre-generated sample `compliance_report.json` |
| POST | `/api/pipeline/run` | Multipart upload (`dossier_pdf`, `qa_pdf`) → full Part 1 + Part 2 result |
| POST | `/api/audit` | JSON body = a populated filing → runs Part 2 only |

---

## 8. Sample files included for testing

- `backend/sample_inputs/Amlodipine_Besylate_14Page_FDA_Dossier.pdf` and
  `Amlodipine_Besylate_QA_Compliance_Package.pdf` — the original two source PDFs, used by the
  **"Run With Bundled Sample Package"** button and by `GET /api/sample/run`.
- `backend/sample_data/regulatoryFiling.json` and `compliance_report.json` — a reference
  Part 1 + Part 2 output pair, generated by running this exact pipeline once, so you can diff
  future runs or inspect the expected shape without starting the server.

### What the reference run finds

Running the bundled sample package produces `REJECTED_HOLD_SUBMISSION`:

- **AML-2026-01** — ✅ `APPROVED_FOR_FILING` (no violations)
- **AML-2026-02** — ❌ `REJECTED_HOLD_SUBMISSION` — CoA assay (97.1%) out of range, Impurity A
  (0.28%) over limit, overall process yield (58.9%) and Step 2 yield (74.1%) both out of
  validated range, Step 2 deprotection time (8.5 h) over the CPP limit, a dossier-vs-CoA assay
  discrepancy (Δ2.5%), two open CRITICAL deviations, one open MAJOR deviation, and an explicit
  QA "REJECT" disposition.
- **AML-2026-03** — ✅ `APPROVED_FOR_FILING` against the configured numeric rules (its
  nitrosamine trend flag is logged as `PENDING CAPA`, not `OPEN`, so it doesn't trip
  `RULE-QA-002` as configured — see the comment above `deviation_rules` in `rules.yaml` if you
  want to tighten that policy).

This matches the QA package's own disposition block (`REJECT Batch AML-2026-02` /
`HOLD Regulatory Filing`), which is exactly what an automated pre-filing audit should catch.

---

## 9. Extending it

- **New GxP rule:** add an entry to `batch_rules` / `deviation_rules` / `disposition_rules` in
  `rules.yaml` — no code change needed.
- **New source document field:** add the field to `regulatoryFiling.schema.json`, extract it in
  the relevant parser function, and thread it through `schema_mapper.py`.
- **A different API/product:** point the same pipeline at a different pair of PDFs (as long as
  their tables follow a comparable layout) and a product-specific `rules.yaml`.

