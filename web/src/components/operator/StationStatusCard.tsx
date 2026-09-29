import { Power, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { api } from "../../lib/api";
import { cx, fmtKw, fmtMin, fmtTime } from "../../lib/format";
import type { OperatorStation } from "../../lib/types";
import { Badge, PriorityBadge, urgencyRing } from "../ui/Badge";
import { Button } from "../ui/Button";
import { LiveDot, LoadBar, PortDots } from "../ui/Meters";
import { useToast } from "../ui/Toast";

const CMD_TONE = { NORMAL: "good", REDUCE_LOAD: "warn", PRIORITIZE_URGENT: "urgent", PAUSE_FLEX: "bad" } as const;

interface Props {
  station: OperatorStation;
  /** Show the grid controls (limit / base load / offline). */
  controls?: boolean;
}

export function StationStatusCard({ station: s, controls }: Props) {
  const toast = useToast();
  const [limit, setLimit] = useState<string>("");
  const [base, setBase] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const patch = async (body: Record<string, unknown>, ok: string) => {
    setBusy(true);
    try {
      await api(`/api/operator/stations/${s.id}`, { method: "PATCH", json: body });
      toast.success(ok);
      setLimit("");
      setBase("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  };
  const hasUrgent = [...s.queue, ...s.active].some((q) => q.priority_class === "urgent");
  const c = s.control;

  return (
    <article data-testid="operator-station" data-station={s.code} className={cx("card overflow-hidden", s.is_chosen_for_latest && "ring-2 ring-brand-500")}>
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3.5 dark:border-ink-700 sm:px-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <LiveDot on={s.is_online} className={s.is_online ? "" : "bg-red-500"} />
            <h3 className="truncate text-base font-bold text-slate-900 dark:text-white">{s.name}</h3>
          </div>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            {s.ports} port{s.ports > 1 ? "s" : ""} × {s.max_kw_per_port} kW · {s.lat.toFixed(4)}, {s.lng.toFixed(4)}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          {s.is_chosen_for_latest && <Badge tone="good">Chosen for latest request</Badge>}
          {hasUrgent && <Badge tone="urgent">Urgent driver</Badge>}
          <Badge tone={s.kind === "physical" ? "good" : "info"}>{s.kind === "physical" ? "Physical" : "Digital twin"}</Badge>
          {!s.is_online && <Badge tone="bad">Offline</Badge>}
        </div>
      </header>

      <div className="space-y-4 p-4 sm:p-5">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Site load / power limit</span>
            <span className="tabular text-sm font-bold text-slate-900 dark:text-white">
              {fmtKw(s.current_load_w)} <span className="font-normal text-slate-500">of {fmtKw(s.site_power_limit_w)}</span>
              <span className={cx("ml-2 text-xs", s.utilization_pct >= 85 ? "text-amber-600" : "text-slate-500")}>{s.utilization_pct}%</span>
            </span>
          </div>
          <LoadBar pct={s.utilization_pct} over={s.over_limit} className="mt-1.5" />
          <div className="mt-1 flex justify-between text-xs text-slate-500">
            <span>Base {s.base_load_kw} kW + EV {s.ev_load_kw} kW</span>
            <span>Headroom {s.headroom_kw} kW</span>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-xl bg-slate-50 p-2.5 dark:bg-ink-800">
            <div className="text-[11px] font-semibold uppercase text-slate-500">Ports</div>
            <div className="mt-1 flex justify-center"><PortDots total={s.ports} busy={s.ports_busy} /></div>
            <div className="tabular text-xs text-slate-600 dark:text-slate-300">{s.available_ports}/{s.ports} free</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-2.5 dark:bg-ink-800">
            <div className="text-[11px] font-semibold uppercase text-slate-500">Queue</div>
            <div className="tabular text-xl font-bold text-slate-900 dark:text-white">{s.queue_count}</div>
          </div>
          <div className="rounded-xl bg-slate-50 p-2.5 dark:bg-ink-800">
            <div className="text-[11px] font-semibold uppercase text-slate-500">Command</div>
            <div className="mt-1">{c && <Badge tone={CMD_TONE[c.command]}>{c.command.replace("_", " ")}</Badge>}</div>
            <div className="text-[11px] text-slate-500">{c?.source === "hardware" ? "hardware" : "simulated"}</div>
          </div>
        </div>

        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Charging now</h4>
          {s.active.length === 0 ? (
            <p className="text-sm text-slate-500">No active sessions.</p>
          ) : (
            <ul className="space-y-1.5">
              {s.active.map((a) => (
                <li key={a.reservation_id} className={cx("flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm", urgencyRing(a.priority_class))}>
                  <span className="flex min-w-0 items-center gap-2"><PriorityBadge priority={a.priority_class} /><span className="truncate font-medium">{a.driver_name}</span></span>
                  <span className="tabular whitespace-nowrap text-xs text-slate-500">{a.kw.toFixed(0)} kW · {fmtMin(a.remaining_min)} left</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Queue</h4>
          {s.queue.length === 0 ? (
            <p className="text-sm text-slate-500">Queue is empty.</p>
          ) : (
            <ol className="space-y-1.5">
              {s.queue.map((q) => (
                <li key={q.reservation_id} className={cx("flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm", urgencyRing(q.priority_class))}>
                  <span className="flex min-w-0 items-center gap-2"><span className="tabular w-5 text-xs font-bold text-slate-400">#{q.position}</span><PriorityBadge priority={q.priority_class} /><span className="truncate font-medium">{q.driver_name}</span></span>
                  <span className="tabular whitespace-nowrap text-xs text-slate-500">{fmtTime(q.planned_start_at)} · in {fmtMin(q.starts_in_min)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {controls && (
          <form
            className="rounded-xl border border-dashed border-slate-300 p-3 dark:border-ink-600"
            onSubmit={(e) => {
              e.preventDefault();
              const body: Record<string, number> = {};
              if (limit !== "") body.site_limit_kw = Number(limit);
              if (base !== "") body.base_load_kw = Number(base);
              if (Object.keys(body).length) void patch(body, "Station updated. Queue re-planned.");
            }}
          >
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500"><SlidersHorizontal className="h-3.5 w-3.5" /> Grid controls</p>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-slate-500">Site limit (kW)
                <input className="input mt-1" type="number" min={1} step="any" placeholder={String(s.site_limit_kw)} value={limit} onChange={(e) => setLimit(e.target.value)} aria-label={`Site limit for ${s.code}`} />
              </label>
              <label className="text-xs text-slate-500">Base load (kW)
                <input className="input mt-1" type="number" min={0} step="any" placeholder={String(s.base_load_kw)} value={base} onChange={(e) => setBase(e.target.value)} aria-label={`Base load for ${s.code}`} />
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="submit" size="sm" loading={busy} disabled={limit === "" && base === ""}>Apply</Button>
              <Button type="button" size="sm" variant={s.is_online ? "danger" : "secondary"} icon={<Power className="h-4 w-4" />} disabled={busy} onClick={() => void patch({ is_online: !s.is_online }, s.is_online ? "Station taken offline" : "Station back online")}>
                {s.is_online ? "Take offline" : "Bring online"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </article>
  );
}
