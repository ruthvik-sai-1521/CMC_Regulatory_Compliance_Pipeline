const API = ""; // same-origin

let state = {
  filing: null,
  report: null,
  dossierFile: null,
  qaFile: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------
async function checkHealth() {
  const pill = $("apiStatusPill");
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    if (data.status === "ok") {
      pill.textContent = "● API online — v" + data.version;
      pill.className = "pill pill-ok";
    } else {
      throw new Error("not ok");
    }
  } catch (e) {
    pill.textContent = "● API unreachable";
    pill.className = "pill pill-bad";
  }
}

// ---------------------------------------------------------------------
// File dropzones
// ---------------------------------------------------------------------
function setupDropzone(zoneId, inputId, labelId, onSelect) {
  const zone = $(zoneId);
  const input = $(inputId);
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("has-file"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("has-file"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      handleFile(e.dataTransfer.files[0]);
    }
  });
  input.addEventListener("change", () => {
    if (input.files.length) handleFile(input.files[0]);
  });
  function handleFile(file) {
    zone.classList.add("has-file");
    $(labelId).textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    onSelect(file);
  }
}

setupDropzone("dossierDrop", "dossierFile", "dossierFileName", (f) => (state.dossierFile = f));
setupDropzone("qaDrop", "qaFile", "qaFileName", (f) => (state.qaFile = f));

// ---------------------------------------------------------------------
// Pipeline runners
// ---------------------------------------------------------------------
$("runSampleBtn").addEventListener("click", () => runPipeline({ useSample: true }));
$("runUploadBtn").addEventListener("click", () => runPipeline({ useSample: false }));

async function runPipeline({ useSample }) {
  hide("errorSection");
  hide("resultsSection");
  show("loadingSection");
  $("loadingTitle").textContent = useSample
    ? "Running pipeline on bundled sample package…"
    : "Parsing uploaded source documents…";
  $("loadingSub").textContent = "Extracting nested CMC tables and cross-referencing dossier vs. QA records.";
  setButtonsDisabled(true);

  try {
    let payload;
    if (useSample) {
      const res = await fetch(`${API}/api/sample/run`);
      if (!res.ok) throw new Error(await res.text());
      payload = await res.json();
    } else {
      const form = new FormData();
      if (state.dossierFile) form.append("dossier_pdf", state.dossierFile);
      if (state.qaFile) form.append("qa_pdf", state.qaFile);
      const res = await fetch(`${API}/api/pipeline/run`, { method: "POST", body: form });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errBody.detail || "Pipeline failed");
      }
      payload = await res.json();
    }
    state.filing = payload.regulatoryFiling;
    state.report = payload.compliance_report;
    await renderResults();
  } catch (e) {
    show("errorSection");
    $("errorText").textContent = e.message || String(e);
  } finally {
    hide("loadingSection");
    setButtonsDisabled(false);
  }
}

function setButtonsDisabled(disabled) {
  $("runSampleBtn").disabled = disabled;
  $("runUploadBtn").disabled = disabled;
}

// ---------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------
async function renderResults() {
  const report = state.report;
  const filing = state.filing;

  // Verdict banner
  const banner = $("verdictBanner");
  const approved = report.final_dossier_verdict === "APPROVED_FOR_FILING";
  banner.className = "verdict-banner " + (approved ? "approved" : "rejected");
  $("verdictValue").textContent = report.final_dossier_verdict.replace(/_/g, " ");
  $("verdictReason").textContent = report.verdict_reason || "";
  $("reportIdLine").textContent = `${report.report_id} · generated ${new Date(report.generated_at).toLocaleString()}`;

  // Stat cards
  const completenessOk = report.data_completeness.status === "PASS";
  $("statCompleteness").innerHTML = `<span class="badge ${completenessOk ? "badge-pass" : "badge-critical"}">${report.data_completeness.status}</span>`;
  $("statCompletenessSub").textContent = completenessOk
    ? `${report.data_completeness.mandatory_sections_checked.length} mandatory sections verified`
    : `Missing: ${report.data_completeness.missing_sections.join(", ")}`;
  $("statRulesEvaluated").textContent = report.rules_evaluated;

  const sev = report.violations_by_severity || {};
  $("sevCritical").textContent = `CRITICAL ${sev.CRITICAL || 0}`;
  $("sevMajor").textContent = `MAJOR ${sev.MAJOR || 0}`;
  $("sevMinor").textContent = `MINOR ${sev.MINOR || 0}`;

  // Batch grid
  const batchGrid = $("batchGrid");
  batchGrid.innerHTML = "";
  Object.entries(report.batch_verdicts || {}).forEach(([bid, v]) => {
    const ok = v.verdict === "APPROVED_FOR_FILING";
    const div = document.createElement("div");
    div.className = "batch-card " + (ok ? "ok" : "bad");
    div.innerHTML = `
      <div class="batch-id">${bid}</div>
      <div class="batch-verdict ${ok ? "ok" : "bad"}">${v.verdict.replace(/_/g, " ")}</div>
      <div class="batch-counts">
        <span><b>${v.critical_count}</b> critical</span>
        <span><b>${v.major_count}</b> major</span>
        <span><b>${v.minor_count}</b> minor</span>
      </div>`;
    batchGrid.appendChild(div);
  });

  // Violations table
  const tbody = $("violationsBody");
  tbody.innerHTML = "";
  const violations = [...(report.rule_violations || [])].sort((a, b) => {
    const order = { CRITICAL: 0, MAJOR: 1, MINOR: 2 };
    return order[a.severity] - order[b.severity];
  });
  violations.forEach((v) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="badge badge-${v.severity.toLowerCase()}">${v.severity}</span></td>
      <td><code>${v.rule_id}</code></td>
      <td>${v.category}</td>
      <td><b>${v.affected_batch}</b></td>
      <td>${v.parameter}</td>
      <td>${v.actual_value}</td>
      <td>${v.expected}</td>
      <td>${v.description}</td>`;
    tbody.appendChild(tr);
  });
  $("noViolationsNote").hidden = violations.length !== 0;
  $("violationsTable").style.display = violations.length === 0 ? "none" : "table";

  // Rules panel
  await renderRules();

  // Raw JSON panels
  $("filingJson").textContent = JSON.stringify(filing, null, 2);
  $("reportJson").textContent = JSON.stringify(report, null, 2);

  show("resultsSection");
  $("resultsSection").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function renderRules() {
  const tbody = $("rulesBody");
  if (tbody.dataset.loaded) return;
  try {
    const res = await fetch(`${API}/api/rules`);
    const rules = await res.json();
    const allRules = [
      ...(rules.batch_rules || []),
      ...(rules.deviation_rules || []),
      ...(rules.disposition_rules || []),
    ];
    tbody.innerHTML = "";
    allRules.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${r.id}</code></td>
        <td>${r.category}</td>
        <td><span class="badge badge-${r.severity.toLowerCase()}">${r.severity}</span></td>
        <td>${r.description}</td>`;
      tbody.appendChild(tr);
    });
    tbody.dataset.loaded = "1";
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Failed to load rules.yaml: ${e.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = true));
    btn.classList.add("active");
    $("panel-" + btn.dataset.tab).hidden = false;
  });
});

// ---------------------------------------------------------------------
// Downloads
// ---------------------------------------------------------------------
function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
$("downloadFilingBtn").addEventListener("click", () => downloadJson(state.filing, "regulatoryFiling.json"));
$("downloadReportBtn").addEventListener("click", () => downloadJson(state.report, "compliance_report.json"));

// ---------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------
function show(id) { $(id).hidden = false; }
function hide(id) { $(id).hidden = true; }

checkHealth();
