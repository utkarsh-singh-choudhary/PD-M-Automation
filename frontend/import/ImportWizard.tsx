"use client";

import { useState } from "react";

const PROXY_PREFIX = "/api/proxy";

// CSRF double-submit token, echoed back on every mutating request here
// (see app/api/proxy/[...path]/route.ts). Import/commit is exactly the
// kind of state-changing action CSRF protection exists for.
function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)pm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

type UploadResult = { upload_id: string; original_filename: string };
type PreviewResult = {
  sheet: string;
  financial_year: string;
  machines_seen: number;
  machines_created: number;
  machines_updated: number;
  pm_plans_created: number;
  pm_plans_updated: number;
  duplicates_skipped: number;
  warnings: string[];
  errors: string[];
};

const SHEET_OPTIONS = ["PM Plan-26-27", "PD Plan", "PD Plan-", "Auto line (Zinc + Alkline)"];

export default function ImportWizard() {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState<UploadResult | null>(null);
  const [sheetName, setSheetName] = useState(SHEET_OPTIONS[0]);
  const [financialYear, setFinancialYear] = useState("26-27");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [committed, setCommitted] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${PROXY_PREFIX}/api/import/excel/upload`, { method: "POST", headers: { "X-CSRF-Token": csrfToken() }, body: form });
      if (!res.ok) throw new Error("Upload failed");
      const data: UploadResult = await res.json();
      setUploaded(data);
      setStep(2);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handlePreview() {
    if (!uploaded) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("upload_id", uploaded.upload_id);
      form.append("sheet_name", sheetName);
      form.append("financial_year", financialYear);
      const res = await fetch(`${PROXY_PREFIX}/api/import/excel/preview`, { method: "POST", headers: { "X-CSRF-Token": csrfToken() }, body: form });
      if (!res.ok) throw new Error("Preview failed");
      const data: PreviewResult = await res.json();
      setPreview(data);
      setStep(4);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCommit() {
    if (!uploaded) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("upload_id", uploaded.upload_id);
      form.append("sheet_name", sheetName);
      form.append("financial_year", financialYear);
      const res = await fetch(`${PROXY_PREFIX}/api/import/excel/commit`, { method: "POST", headers: { "X-CSRF-Token": csrfToken() }, body: form });
      if (!res.ok) throw new Error("Import failed");
      const data: PreviewResult = await res.json();
      setCommitted(data);
      setStep(7);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">Import PM Plan</h1>
        <p className="text-sm text-muted">Upload the company's PM Excel file and import it into the system.</p>
      </div>

      {error && (
        <div className="bg-red-50 text-bad text-sm px-4 py-2 rounded-sm border border-red-200">{error}</div>
      )}

      <Steps current={step} />

      {step === 1 && (
        <div className="kpi-card gap-3">
          <label className="text-sm font-medium">Step 1 — Upload Excel</label>
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="text-sm"
          />
          <button
            disabled={!file || loading}
            onClick={handleUpload}
            className="self-start mt-2 bg-accent text-white text-sm px-4 py-2 rounded-sm disabled:opacity-50"
          >
            {loading ? "Uploading…" : "Upload"}
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="kpi-card gap-3">
          <label className="text-sm font-medium">Step 2 — Select Sheet</label>
          <select
            value={sheetName}
            onChange={(e) => setSheetName(e.target.value)}
            className="border border-border rounded-sm text-sm px-2 py-1.5 w-fit"
          >
            {SHEET_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <label className="text-sm font-medium mt-2">Financial Year</label>
          <input
            value={financialYear}
            onChange={(e) => setFinancialYear(e.target.value)}
            placeholder="26-27"
            className="border border-border rounded-sm text-sm px-2 py-1.5 w-32"
          />
          <button
            disabled={loading}
            onClick={handlePreview}
            className="self-start mt-2 bg-accent text-white text-sm px-4 py-2 rounded-sm disabled:opacity-50"
          >
            {loading ? "Parsing…" : "Detect Columns & Preview"}
          </button>
        </div>
      )}

      {step === 4 && preview && (
        <div className="space-y-4">
          <div className="kpi-card">
            <label className="text-sm font-medium mb-2">Steps 3–5 — Detected Columns, Preview & Validation</label>
            <div className="grid grid-cols-3 gap-3 text-sm mt-2">
              <SummaryStat label="Machines seen" value={preview.machines_seen} />
              <SummaryStat label="New machines" value={preview.machines_created} />
              <SummaryStat label="Updated machines" value={preview.machines_updated} />
              <SummaryStat label="New PM plans" value={preview.pm_plans_created} />
              <SummaryStat label="Updated PM plans" value={preview.pm_plans_updated} />
              <SummaryStat label="Duplicates skipped" value={preview.duplicates_skipped} />
            </div>
          </div>

          {preview.warnings.length > 0 && (
            <div className="kpi-card border-amber-300">
              <div className="text-sm font-medium text-warn mb-2">Warnings ({preview.warnings.length})</div>
              <ul className="text-xs text-muted space-y-1 max-h-40 overflow-auto">
                {preview.warnings.map((w, i) => <li key={i}>• {w}</li>)}
              </ul>
            </div>
          )}
          {preview.errors.length > 0 && (
            <div className="kpi-card border-red-300">
              <div className="text-sm font-medium text-bad mb-2">Errors ({preview.errors.length})</div>
              <ul className="text-xs text-muted space-y-1 max-h-40 overflow-auto">
                {preview.errors.map((w, i) => <li key={i}>• {w}</li>)}
              </ul>
            </div>
          )}

          <button
            disabled={loading}
            onClick={handleCommit}
            className="bg-accent text-white text-sm px-4 py-2 rounded-sm disabled:opacity-50"
          >
            {loading ? "Importing…" : "Step 6 — Confirm & Import"}
          </button>
        </div>
      )}

      {step === 7 && committed && (
        <div className="kpi-card border-green-300">
          <div className="text-sm font-medium text-good mb-2">Step 7 — Import Summary</div>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <SummaryStat label="Machines" value={committed.machines_created + committed.machines_updated} />
            <SummaryStat label="PM plans created" value={committed.pm_plans_created} />
            <SummaryStat label="Updated" value={committed.pm_plans_updated} />
            <SummaryStat label="Duplicates skipped" value={committed.duplicates_skipped} />
            <SummaryStat label="Warnings" value={committed.warnings.length} />
            <SummaryStat label="Errors" value={committed.errors.length} />
          </div>
        </div>
      )}
    </div>
  );
}

function Steps({ current }: { current: number }) {
  const labels = ["Upload", "Select Sheet", "Detect", "Preview", "Validate", "Import", "Summary"];
  return (
    <div className="flex gap-2 text-xs">
      {labels.map((l, i) => {
        const n = i + 1;
        const active = n === current || (current === 4 && n <= 5) || (current === 7 && n <= 7);
        return (
          <div key={l} className={`px-2 py-1 rounded-sm border ${active ? "bg-accent text-white border-accent" : "border-border text-muted"}`}>
            {n}. {l}
          </div>
        );
      })}
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="kpi-label">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
