import { cx } from "../../lib/format";
import type { OperatorState } from "../../lib/types";
import { StationStatusCard } from "./StationStatusCard";

const COLOR = { urgent: "bg-rose-500", normal: "bg-sky-500", flexible: "bg-slate-400" } as const;

/** Next-two-hours schedule per station: solid = charging now, hatched = queued, red = urgent. */
export function Timeline({ state }: { state: OperatorState }) {
  const horizon = state.timeline.horizon_min;
  const LANE = 30;
  return (
    <div className="card card-pad">
      <h3 className="text-sm font-bold text-slate-900 dark:text-white">Schedule — next {horizon / 60} hours</h3>
      <div className="mt-3 space-y-3">
        {state.stations.map((st) => {
          const items = state.timeline.items.filter((i) => i.station_id === st.id).sort((a, b) => a.start_min - b.start_min);
          const ends: number[] = [];
          const placed = items.map((i) => {
            let lane = ends.findIndex((e) => e <= i.start_min + 0.01);
            if (lane < 0) lane = ends.length;
            ends[lane] = i.end_min;
            return { i, lane };
          });
          return (
            <div key={st.id} className="grid items-center gap-2 sm:grid-cols-[110px_1fr]">
              <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">{st.code} <span className="font-normal text-slate-400">{st.kind}</span></div>
              <div className="relative rounded-lg bg-slate-100 dark:bg-ink-800" style={{ height: Math.max(1, ends.length) * LANE + 4 }} role="img" aria-label={`Schedule for ${st.name}`}>
                {placed.map(({ i, lane }) => (
                  <div
                    key={i.reservation_id}
                    title={`${i.driver_name} · ${i.status} · ${i.allocated_kw.toFixed(0)} kW · ${Math.round(i.start_min)}–${Math.round(i.end_min)} min`}
                    className={cx("absolute overflow-hidden text-ellipsis whitespace-nowrap rounded-md px-2 text-[11px] font-medium leading-[26px] text-white", COLOR[i.priority_class], i.status === "queued" && "opacity-70 [background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.28)_0_6px,transparent_6px_12px)]")}
                    style={{ left: `${(i.start_min / horizon) * 100}%`, width: `${Math.max(2, ((i.end_min - i.start_min) / horizon) * 100)}%`, top: 4 + lane * LANE, height: LANE - 4 }}
                  >
                    {i.driver_name}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        <div className="flex justify-between text-[11px] text-slate-500 sm:pl-[118px]">
          {[0, 30, 60, 90, 120].map((m) => <span key={m}>{m === 0 ? "now" : `+${m} min`}</span>)}
        </div>
      </div>
    </div>
  );
}

export function QueueBoard({ state }: { state: OperatorState }) {
  return (
    <div className="space-y-5">
      <Timeline state={state} />
      <div className="grid gap-5 lg:grid-cols-2">
        {state.stations.map((s) => <StationStatusCard key={s.id} station={s} />)}
      </div>
    </div>
  );
}
