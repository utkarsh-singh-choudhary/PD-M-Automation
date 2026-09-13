"use client";

import { useEffect, useState } from "react";
import { api, AppSettingRow } from "@/lib/api";

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<AppSettingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .adminSettings()
      .then((rows) => {
        setSettings(rows);
        const d: Record<string, string> = {};
        rows.forEach((r) => (d[r.key] = JSON.stringify(r.value, null, 2)));
        setDrafts(d);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(key: string) {
    setSavingKey(key);
    setError(null);
    try {
      let parsed: any;
      try {
        parsed = JSON.parse(drafts[key]);
      } catch {
        throw new Error("Value must be valid JSON (e.g. 7, or [\"a\",\"b\"], or {...})");
      }
      const updated = await api.updateAdminSetting(key, parsed);
      setSettings((prev) => prev.map((s) => (s.key === key ? { ...s, value: updated.value } : s)));
    } catch (e: any) {
      setError(e.message || "Failed to save");
    } finally {
      setSavingKey(null);
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-3xl">
      <div>
        <h1 className="text-lg font-semibold text-ink">Admin Settings</h1>
        <p className="text-sm text-muted">
          Reminder day-offsets, escalation thresholds, and the week→calendar-date convention.
          Changes take effect on the next scheduled job run — no deploy needed.
        </p>
      </div>

      {error && (
        <div className="text-xs text-bad bg-red-50 border border-red-100 rounded-sm px-3 py-2">{error}</div>
      )}

      {loading ? (
        <div className="text-sm text-muted">Loading…</div>
      ) : (
        <div className="space-y-4">
          {settings.map((s) => (
            <div key={s.key} className="kpi-card gap-2">
              <div className="flex items-baseline justify-between">
                <div className="font-mono text-sm font-medium text-ink">{s.key}</div>
                <div className="text-[11px] text-muted">default: {JSON.stringify(s.default)}</div>
              </div>
              <div className="text-xs text-muted">{s.description}</div>
              <textarea
                value={drafts[s.key] ?? ""}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [s.key]: e.target.value }))}
                className="border border-border rounded-sm px-3 py-2 text-sm font-mono"
                rows={s.key === "escalation_thresholds" ? 6 : 2}
              />
              <button
                onClick={() => handleSave(s.key)}
                disabled={savingKey === s.key}
                className="self-start bg-ink text-white text-xs rounded-sm px-3 py-1.5 hover:opacity-90 disabled:opacity-50"
              >
                {savingKey === s.key ? "Saving…" : "Save"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
