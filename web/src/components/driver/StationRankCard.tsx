import { CalendarCheck, Clock, Route, Timer, Zap } from "lucide-react";
import { cx, fmtKw, fmtMin, fmtTime } from "../../lib/format";
import type { PublicStation, RankingEntry } from "../../lib/types";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { LoadBar, PortDots } from "../ui/Meters";
import { ScoreBar } from "./ScoreBar";

interface Props {
  entry: RankingEntry;
  best: boolean;
  maxScore: number;
  live: PublicStation | undefined; // real-time availability pushed over the WebSocket
  estimated: boolean;
  disabled: boolean; // e.g. the driver already has an open reservation
  reserving: boolean;
  onReserve: (stationId: number) => void;
}

function Metric({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-2.5 dark:bg-ink-800">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {icon}
        {label}
      </div>
      <div className="tabular mt-0.5 text-base font-bold text-slate-900 dark:text-white">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

export function StationRankCard({ entry, best, maxScore, live, estimated, disabled, reserving, onReserve }: Props) {
  const st = live?.state ?? entry.station_state;
  const ports = live?.ports ?? st.available_ports;
  const busy = live ? live.ports_busy : 0;
  const util = live?.utilization_pct ?? (st.site_power_limit_w ? (st.current_load_w / st.site_power_limit_w) * 100 : 0);

  return (
    <article
      data-testid="station-card"
      data-station={entry.code}
      className={cx("card overflow-hidden", best && "ring-2 ring-brand-500", !entry.feasible && "opacity-75")}
    >
      {best && (
        <div className="flex items-center gap-2 bg-brand-600 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-white dark:bg-brand-500 dark:text-ink-950">
          <Zap className="h-3.5 w-3.5" fill="currentColor" /> Best choice for you
        </div>
      )}
      <div className="card-pad space-y-3.5">
        <header className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-100 text-sm font-bold text-slate-700 dark:bg-ink-700 dark:text-slate-200">{entry.rank}</span>
            <div className="min-w-0">
              <h3 className="truncate text-base font-bold text-slate-900 dark:text-white">{entry.name}</h3>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <Badge tone={entry.kind === "physical" ? "good" : "info"}>{entry.kind === "physical" ? "Physical rig" : "Digital twin"}</Badge>
                {live && !live.is_online && <Badge tone="bad">Offline</Badge>}
                {entry.feasible && entry.deadline_ok === false && <Badge tone="warn">Misses deadline</Badge>}
              </div>
            </div>
          </div>
          {entry.feasible && entry.final_score !== null && (
            <div className="text-right">
              <div className="tabular text-2xl font-extrabold leading-none text-slate-900 dark:text-white">{entry.final_score}</div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">score</div>
            </div>
          )}
        </header>

        {entry.feasible ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric icon={<Route className="h-3.5 w-3.5" />} label="Travel" value={fmtMin(entry.travel_time_min)} sub={`${entry.distance_km.toFixed(1)} km${estimated ? " · estimated" : ""}`} />
              <Metric icon={<Timer className="h-3.5 w-3.5" />} label="Wait" value={fmtMin(entry.predicted_wait_min)} sub={st.queue_count ? `${st.queue_count} in queue` : "No queue"} />
              <Metric icon={<Zap className="h-3.5 w-3.5" />} label="Charge" value={fmtMin(entry.charge_time_min)} sub={`at ${entry.charge_kw.toFixed(0)} kW`} />
              <Metric icon={<Clock className="h-3.5 w-3.5" />} label="Ready at" value={fmtTime(entry.ready_at)} sub={`total ${fmtMin(entry.total_time_min)}`} />
            </div>
            {entry.score_breakdown && <ScoreBar breakdown={entry.score_breakdown} max={maxScore} />}
          </>
        ) : (
          <p className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-ink-800 dark:text-slate-300">
            <span className="font-semibold">Not usable:</span> {entry.rejection_reason}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs text-slate-600 dark:border-ink-700 dark:text-slate-300">
          <span className="inline-flex items-center gap-2">
            <PortDots total={ports} busy={busy} />
            {live ? `${live.available_ports}/${live.ports} ports free` : `${st.available_ports} free`}
          </span>
          <span className="inline-flex min-w-[9rem] flex-1 items-center gap-2 sm:max-w-[16rem]">
            <LoadBar pct={util} over={live?.over_limit} className="flex-1" />
            <span className="tabular whitespace-nowrap">
              {fmtKw(st.current_load_w)} / {fmtKw(st.site_power_limit_w)}
            </span>
          </span>
        </div>

        {entry.feasible && (
          <Button
            block
            variant={best ? "primary" : "secondary"}
            onClick={() => onReserve(entry.station_id)}
            loading={reserving}
            disabled={disabled}
            icon={<CalendarCheck className="h-4 w-4" />}
          >
            {disabled ? "You already have a reservation" : `Reserve at ${entry.code}`}
          </Button>
        )}
      </div>
    </article>
  );
}
