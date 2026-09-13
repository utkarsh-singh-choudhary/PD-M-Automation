export function KpiCard({ label, value, tone }: { label: string; value: string | number; tone?: "good" | "warn" | "bad" }) {
  const toneClass = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-ink";
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${toneClass}`}>{value}</div>
    </div>
  );
}
