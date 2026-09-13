import { api, PMPlan } from "@/lib/api";
import { KpiCard } from "@/components/KpiCard";
import { StatusPill } from "@/components/StatusPill";
import Link from "next/link";

export const dynamic = "force-dynamic";

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}

export default async function DashboardPage() {
  const [machines, upcoming, overdue, allPlans] = await Promise.all([
    safe(() => api.machines(), []),
    safe(() => api.pmUpcoming(14), []),
    safe(() => api.pmOverdue(), []),
    safe(() => api.pmAll(), []),
  ]);

  const completed = allPlans.filter((p) => p.status === "COMPLETED").length;
  const planned = allPlans.length;
  const completionPct = planned ? Math.round((completed / planned) * 100) : 0;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">Preventive Maintenance Dashboard</h1>
        <p className="text-sm text-muted">Live status across all machines, FY 26-27.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label="Total Machines" value={machines.length} />
        <KpiCard label="PM Planned" value={planned} />
        <KpiCard label="PM Completed" value={completed} tone="good" />
        <KpiCard label="PM Upcoming (14d)" value={upcoming.length} tone="warn" />
        <KpiCard label="PM Overdue" value={overdue.length} tone={overdue.length ? "bad" : "good"} />
        <KpiCard label="Completion %" value={`${completionPct}%`} tone={completionPct >= 90 ? "good" : "warn"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PlanTable title="Upcoming Maintenance" plans={upcoming} emptyText="No PM due in the next 14 days." />
        <PlanTable title="Overdue Maintenance" plans={overdue} emptyText="Nothing overdue." highlightOverdue />
      </div>
    </div>
  );
}

function PlanTable({
  title,
  plans,
  emptyText,
  highlightOverdue,
}: {
  title: string;
  plans: PMPlan[];
  emptyText: string;
  highlightOverdue?: boolean;
}) {
  return (
    <div className="kpi-card !p-0 overflow-hidden">
      <div className="px-4 py-3 border-b border-border font-medium text-sm">{title}</div>
      {plans.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted">{emptyText}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Machine</th>
              <th>Planned Date</th>
              <th>Month</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.id}>
                <td className="font-mono text-xs">{p.machine_id.slice(0, 8)}</td>
                <td>{p.planned_date || "—"}</td>
                <td>{p.month}</td>
                <td>
                  <StatusPill status={highlightOverdue ? "OVERDUE" : p.status} />
                </td>
                <td>
                  {p.status !== "COMPLETED" && p.status !== "CANCELLED" && (
                    <Link href={`/pm/${p.id}/complete`} className="text-xs text-accent hover:underline">
                      Complete
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
