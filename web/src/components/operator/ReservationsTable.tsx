import { X } from "lucide-react";
import { useState } from "react";
import { api } from "../../lib/api";
import { cx, fmtMin, fmtTime } from "../../lib/format";
import type { Reservation } from "../../lib/types";
import { Badge, PriorityBadge, urgencyRing } from "../ui/Badge";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/Card";
import { Segmented } from "../ui/Segmented";
import { useToast } from "../ui/Toast";

type Filter = "open" | "urgent" | "history";

const TONE = { queued: "info", active: "good", done: "neutral", cancelled: "warn" } as const;

export function ReservationsTable({ open, finished }: { open: Reservation[]; finished: Reservation[] }) {
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("open");
  const [busy, setBusy] = useState<number | null>(null);

  const rows = filter === "history" ? finished : filter === "urgent" ? open.filter((r) => r.priority_class === "urgent") : open;
  const cancel = async (id: number) => {
    setBusy(id);
    try {
      await api(`/api/operator/reservations/${id}/cancel`, { method: "POST" });
      toast.success(`Reservation #${id} cancelled`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not cancel");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <Segmented label="Reservation filter" value={filter} onChange={setFilter} options={[
        { value: "open", label: `Open (${open.length})` },
        { value: "urgent", label: `Urgent (${open.filter((r) => r.priority_class === "urgent").length})` },
        { value: "history", label: "Recent history" },
      ]} />
      {rows.length === 0 ? (
        <EmptyState title="Nothing here">No reservations match this filter.</EmptyState>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-ink-700">
              <tr>{["#", "Driver", "Station", "Priority", "Status", "Arrives", "Starts", "Ends", "Power", ""].map((h) => <th key={h} className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody data-testid="reservation-rows">
              {rows.map((r) => (
                <tr key={r.id} className={cx("border-b border-slate-100 last:border-0 dark:border-ink-700", urgencyRing(r.priority_class))}>
                  <td className="tabular px-3 py-2.5 text-slate-500">{r.id}</td>
                  <td className="px-3 py-2.5 font-medium text-slate-900 dark:text-white">{r.driver_name}</td>
                  <td className="px-3 py-2.5">{r.station_code}</td>
                  <td className="px-3 py-2.5"><PriorityBadge priority={r.priority_class} /></td>
                  <td className="px-3 py-2.5"><Badge tone={TONE[r.status]} dot>{r.status}{r.queue_position ? ` #${r.queue_position}` : ""}</Badge></td>
                  <td className="tabular px-3 py-2.5">{fmtTime(r.arrival_at)}</td>
                  <td className="tabular px-3 py-2.5">{fmtTime(r.planned_start_at)}<span className="block text-[11px] text-slate-400">{r.status === "queued" ? `in ${fmtMin((new Date(r.planned_start_at).getTime() - Date.now()) / 60000)}` : ""}</span></td>
                  <td className="tabular px-3 py-2.5">{fmtTime(r.planned_end_at)}</td>
                  <td className="tabular px-3 py-2.5">{r.allocated_kw.toFixed(0)} kW</td>
                  <td className="px-3 py-2.5 text-right">
                    {(r.status === "queued" || r.status === "active") && (
                      <Button size="sm" variant="danger" loading={busy === r.id} icon={<X className="h-3.5 w-3.5" />} onClick={() => void cancel(r.id)} aria-label={`Cancel reservation ${r.id}`}>Cancel</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
