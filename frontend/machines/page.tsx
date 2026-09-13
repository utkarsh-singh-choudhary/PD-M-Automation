import { api } from "@/lib/api";
import { StatusPill } from "@/components/StatusPill";

export const dynamic = "force-dynamic";

export default async function MachinesPage() {
  let machines: Awaited<ReturnType<typeof api.machines>> = [];
  try {
    machines = await api.machines();
  } catch {
    machines = [];
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">Machines</h1>
        <p className="text-sm text-muted">{machines.length} active machines.</p>
      </div>

      <div className="kpi-card !p-0 overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th>M/c No.</th>
              <th>Name</th>
              <th>Manufacturer</th>
              <th>Location</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {machines.map((m) => (
              <tr key={m.id}>
                <td className="font-medium">{m.machine_number}</td>
                <td>{m.machine_name} {m.critical && <span className="text-bad">*</span>}</td>
                <td>{m.manufacturer || "—"}</td>
                <td>{m.location || "—"}</td>
                <td><StatusPill status={m.active ? "PLANNED" : "CANCELLED"} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
