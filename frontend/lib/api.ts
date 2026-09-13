// Every call here goes through the same-origin BFF proxy at /api/proxy/*,
// which attaches the HttpOnly JWT server-side (see
// app/api/proxy/[...path]/route.ts). No Authorization header is set here -
// client JS never has the token - the browser just sends the pm_token
// cookie along automatically since this is a same-origin request, and the
// proxy does the rest.
const PROXY_PREFIX = "/api/proxy";

export type Machine = {
  id: string;
  machine_number: string;
  machine_name: string;
  manufacturer?: string;
  specification?: string;
  location?: string;
  remarks?: string;
  critical: boolean;
  active: boolean;
};

export type PMPlan = {
  id: string;
  machine_id: string;
  planned_date?: string;
  planned_week?: string;
  month: string;
  financial_year: string;
  status: string;
  low_confidence_actual: boolean;
};

export type ChecklistItem = {
  id: string;
  sequence: number;
  text: string;
  required: boolean;
};

export type ChecklistForMachine = {
  template_id: string | null;
  items: ChecklistItem[];
};

export type AppSettingRow = {
  key: string;
  value: any;
  default: any;
  description: string;
};

// Reads the non-HttpOnly pm_csrf cookie (set at login, see
// app/api/auth/login/route.ts) so state-changing requests can echo it back
// as a header - the proxy route rejects any POST/PUT/PATCH/DELETE where
// this doesn't match the cookie it holds (CSRF double-submit defense).
function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)pm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${PROXY_PREFIX}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

async function apiPut<T>(path: string, body: any): Promise<T> {
  const res = await fetch(`${PROXY_PREFIX}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() ?? "" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

export const api = {
  machines: () => apiGet<Machine[]>("/api/machines"),
  pmUpcoming: (days = 14) => apiGet<PMPlan[]>(`/api/pm/upcoming?days=${days}`),
  pmOverdue: () => apiGet<PMPlan[]>("/api/pm/overdue"),
  pmAll: () => apiGet<PMPlan[]>("/api/pm"),
  pmById: (id: string) => apiGet<PMPlan>(`/api/pm/${id}`),
  checklistForMachine: (machineId: string) => apiGet<ChecklistForMachine>(`/api/checklists/for-machine/${machineId}`),
  health: () => apiGet<Record<string, string>>("/health"),
  auditLogs: () => apiGet<any[]>("/api/audit-logs"),

  adminSettings: () => apiGet<AppSettingRow[]>("/api/admin/settings"),
  updateAdminSetting: (key: string, value: any) => apiPut<{ key: string; value: any }>(`/api/admin/settings/${key}`, { value }),

  async completePM(
    pmId: string,
    payload: {
      actual_date: string;
      remarks?: string;
      delay_reason?: string;
      downtime_minutes?: number;
      checklist_responses?: { item_id: string; checked: boolean; note?: string }[];
    },
    file?: File | null
  ) {
    const form = new FormData();
    form.set("actual_date", payload.actual_date);
    if (payload.remarks) form.set("remarks", payload.remarks);
    if (payload.delay_reason) form.set("delay_reason", payload.delay_reason);
    if (payload.downtime_minutes != null) form.set("downtime_minutes", String(payload.downtime_minutes));
    // Only sent when the machine actually has a checklist template - the
    // backend treats an empty/missing value the same as "no checklist"
    // (Critical #3 fix: the frontend previously never sent this field at
    // all, so any machine with a required checklist item would 400 on
    // every completion attempt).
    if (payload.checklist_responses) {
      form.set("checklist_responses", JSON.stringify(payload.checklist_responses));
    }
    if (file) form.set("attachment", file);

    const res = await fetch(`${PROXY_PREFIX}/api/pm/${pmId}/complete`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() ?? "" },
      body: form,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail || `Failed to complete PM (${res.status})`);
    }
    return res.json();
  },
};
