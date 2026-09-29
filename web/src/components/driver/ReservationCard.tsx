import { CalendarClock, MapPin, X } from "lucide-react";
import { cx, fmtMin, fmtTime } from "../../lib/format";
import type { Reservation } from "../../lib/types";
import { Badge, PriorityBadge, type Tone } from "../ui/Badge";
import { Button } from "../ui/Button";

const STATUS: Record<Reservation["status"], { label: string; tone: Tone }> = {
  queued: { label: "In queue", tone: "info" },
  active: { label: "Charging now", tone: "good" },
  done: { label: "Completed", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "warn" },
};

/** Minutes until an ISO time, computed on the client so it ticks between pushes. */
const minutesUntil = (iso: string) => (new Date(iso).getTime() - Date.now()) / 60_000;

export function ReservationCard({ r, onCancel, cancelling }: { r: Reservation; onCancel?: (id: number) => void; cancelling?: boolean }) {
  const s = STATUS[r.status];
  const open = r.status === "queued" || r.status === "active";
  const toStart = Math.max(0, minutesUntil(r.planned_start_at));
  const toEnd = Math.max(0, minutesUntil(r.planned_end_at));

  return (
    <article data-testid="reservation-card" data-status={r.status} className={cx("card card-pad space-y-3", open && "ring-1 ring-brand-500/40")}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
            <MapPin className="h-4 w-4 text-brand-600" />
            <span className="truncate">{r.station_name}</span>
          </div>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Reservation #{r.id}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <PriorityBadge priority={r.priority_class} />
          <Badge tone={s.tone} dot>
            {r.status === "queued" && r.queue_position ? `${s.label} · #${r.queue_position}` : s.label}
          </Badge>
        </div>
      </header>

      <dl className="grid grid-cols-3 gap-2 text-center">
        {[
          ["Arrive", fmtTime(r.arrival_at)],
          ["Charging starts", fmtTime(r.planned_start_at)],
          ["Ends", fmtTime(r.planned_end_at)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl bg-slate-50 p-2 dark:bg-ink-800">
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{k}</dt>
            <dd className="tabular text-sm font-bold text-slate-900 dark:text-white">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600 dark:text-slate-300">
        <span className="inline-flex items-center gap-1.5">
          <CalendarClock className="h-4 w-4" />
          {r.status === "queued" && `Your turn in ${fmtMin(toStart)}`}
          {r.status === "active" && `${fmtMin(toEnd)} of charging left`}
          {r.status === "done" && "Charging finished"}
          {r.status === "cancelled" && "Reservation cancelled"}
          {open && <span className="text-slate-400">· {r.allocated_kw.toFixed(0)} kW allocated</span>}
        </span>
        {open && onCancel && (
          <Button variant="danger" size="sm" icon={<X className="h-4 w-4" />} loading={cancelling} onClick={() => onCancel(r.id)}>
            Cancel
          </Button>
        )}
      </div>
    </article>
  );
}
