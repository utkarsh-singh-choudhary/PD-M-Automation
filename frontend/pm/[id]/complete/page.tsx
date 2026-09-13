"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ChecklistItem } from "@/lib/api";

export default function CompletePMPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [actualDate, setActualDate] = useState(new Date().toISOString().slice(0, 10));
  const [remarks, setRemarks] = useState("");
  const [delayReason, setDelayReason] = useState("");
  const [downtime, setDowntime] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // Checklist state (Critical #3 fix: the completion screen previously
  // never fetched or submitted a machine's checklist at all, so any
  // machine with a required item would always 400 on submit).
  const [checklistLoading, setChecklistLoading] = useState(true);
  const [checklistError, setChecklistError] = useState<string | null>(null);
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    async function loadChecklist() {
      setChecklistLoading(true);
      setChecklistError(null);
      try {
        const plan = await api.pmById(id);
        const template = await api.checklistForMachine(plan.machine_id);
        if (cancelled) return;
        setItems(template.items);
      } catch (err: any) {
        if (!cancelled) {
          // Non-fatal: a machine with no checklist template is the normal
          // case, and completePM still works fine with an empty list. Only
          // surface this if it looks like a real failure vs "no checklist".
          setChecklistError(err.message || "Could not load checklist for this machine");
        }
      } finally {
        if (!cancelled) setChecklistLoading(false);
      }
    }
    loadChecklist();
    return () => {
      cancelled = true;
    };
  }, [id]);

  function toggleItem(itemId: string) {
    setChecked((prev) => ({ ...prev, [itemId]: !prev[itemId] }));
  }

  const missingRequired = items.filter((i) => i.required && !checked[i.id]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (missingRequired.length > 0) {
      setError(
        `Please check all required items before submitting: ${missingRequired
          .map((i) => i.text)
          .join(", ")}`
      );
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const checklist_responses = items.map((i) => ({
        item_id: i.id,
        checked: !!checked[i.id],
        note: notes[i.id] || undefined,
      }));
      await api.completePM(
        id,
        {
          actual_date: actualDate,
          remarks: remarks || undefined,
          delay_reason: delayReason || undefined,
          downtime_minutes: downtime ? Number(downtime) : undefined,
          checklist_responses: items.length > 0 ? checklist_responses : undefined,
        },
        file
      );
      setDone(true);
      setTimeout(() => router.push("/dashboard"), 1200);
    } catch (err: any) {
      setError(err.message || "Failed to complete PM");
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="p-6">
        <div className="kpi-card text-good text-sm">PM marked complete. Redirecting…</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-lg space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">Complete Preventive Maintenance</h1>
        <p className="text-sm text-muted">PM Plan ID: <span className="font-mono">{id}</span></p>
      </div>

      <form onSubmit={handleSubmit} className="kpi-card gap-4">
        {error && (
          <div className="text-xs text-bad bg-red-50 border border-red-100 rounded-sm px-3 py-2">{error}</div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Actual completion date</label>
          <input
            type="date"
            required
            value={actualDate}
            onChange={(e) => setActualDate(e.target.value)}
            className="border border-border rounded-sm px-3 py-2 text-sm"
          />
        </div>

        {checklistLoading && (
          <div className="text-xs text-muted">Loading checklist…</div>
        )}

        {!checklistLoading && checklistError && (
          <div className="text-xs text-bad bg-red-50 border border-red-100 rounded-sm px-3 py-2">
            {checklistError}
          </div>
        )}

        {!checklistLoading && items.length > 0 && (
          <div className="flex flex-col gap-2 border border-border rounded-sm p-3">
            <label className="text-xs text-muted font-medium">
              PM Checklist — required items must be checked before you can submit
            </label>
            {items
              .slice()
              .sort((a, b) => a.sequence - b.sequence)
              .map((item) => (
                <div key={item.id} className="flex flex-col gap-1 border-b border-border/50 pb-2 last:border-0">
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={!!checked[item.id]}
                      onChange={() => toggleItem(item.id)}
                      className="mt-0.5"
                    />
                    <span>
                      {item.text}
                      {item.required && <span className="text-bad"> *</span>}
                    </span>
                  </label>
                  <input
                    placeholder="Note (optional)"
                    value={notes[item.id] || ""}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [item.id]: e.target.value }))}
                    className="border border-border rounded-sm px-2 py-1 text-xs ml-6"
                  />
                </div>
              ))}
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Remarks</label>
          <textarea
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            className="border border-border rounded-sm px-3 py-2 text-sm"
            rows={3}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Delay reason (if late)</label>
          <input
            value={delayReason}
            onChange={(e) => setDelayReason(e.target.value)}
            className="border border-border rounded-sm px-3 py-2 text-sm"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Downtime (minutes)</label>
          <input
            type="number"
            min={0}
            value={downtime}
            onChange={(e) => setDowntime(e.target.value)}
            className="border border-border rounded-sm px-3 py-2 text-sm"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">
            Proof of work (photo or PDF) — audits look for this
          </label>
          <input
            type="file"
            accept=".jpg,.jpeg,.png,.pdf,.heic,.webp"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="text-sm"
          />
        </div>

        <button
          type="submit"
          disabled={loading || checklistLoading}
          className="bg-ink text-white text-sm rounded-sm py-2 hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Submitting…" : "Mark Complete"}
        </button>
      </form>
    </div>
  );
}
