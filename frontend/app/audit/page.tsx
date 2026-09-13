"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function AuditLogPage() {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .auditLogs()
      .then(setLogs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">Audit Log</h1>
        <p className="text-sm text-muted">Who changed what, and when.</p>
      </div>

      {error && (
        <div className="text-xs text-bad bg-red-50 border border-red-100 rounded-sm px-3 py-2">{error}</div>
      )}

      {loading ? (
        <div className="text-sm text-muted">Loading…</div>
      ) : (
        <div className="kpi-card !p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Actor</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="text-xs">{l.created_at}</td>
                  <td className="text-xs font-medium">{l.action}</td>
                  <td className="text-xs">
                    {l.entity_type} {l.entity_id ? `#${String(l.entity_id).slice(0, 8)}` : ""}
                  </td>
                  <td className="text-xs font-mono">{l.actor_id ? l.actor_id.slice(0, 8) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
