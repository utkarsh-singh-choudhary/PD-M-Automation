const COLORS: Record<string, string> = {
  PLANNED: "bg-blue-50 text-blue-700",
  REMINDER_SENT: "bg-blue-50 text-blue-700",
  DUE: "bg-amber-50 text-amber-800",
  IN_PROGRESS: "bg-amber-50 text-amber-800",
  COMPLETED: "bg-green-50 text-good",
  OVERDUE: "bg-red-50 text-bad",
  MISSED: "bg-red-50 text-bad",
  CANCELLED: "bg-gray-100 text-muted",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`status-pill ${COLORS[status] || "bg-gray-100 text-muted"}`}>
      {status.replace("_", " ")}
    </span>
  );
}
