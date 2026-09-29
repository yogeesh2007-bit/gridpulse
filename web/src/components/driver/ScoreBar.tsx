import type { ScoreBreakdown } from "../../lib/types";

const PARTS = [
  { key: "travel_time", label: "Travel", color: "bg-sky-500" },
  { key: "predicted_wait", label: "Wait", color: "bg-amber-500" },
  { key: "charging_time", label: "Charge", color: "bg-brand-500" },
  { key: "load_penalty", label: "Load penalty", color: "bg-rose-400" },
] as const;

/** Stacked bar of the four cost terms (minutes) with the urgency bonus called out. */
export function ScoreBar({ breakdown, max }: { breakdown: ScoreBreakdown; max: number }) {
  const total = PARTS.reduce((s, p) => s + breakdown[p.key], 0);
  const scale = max > 0 ? 100 / max : 0;
  return (
    <div>
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-ink-700"
        role="img"
        aria-label={`Score: ${breakdown.travel_time} travel, ${breakdown.predicted_wait} wait, ${breakdown.charging_time} charge, ${breakdown.load_penalty} load penalty, minus ${breakdown.urgency_bonus} urgency bonus, equals ${breakdown.final_score}`}
      >
        {PARTS.map((p) => (
          <div key={p.key} className={p.color} style={{ width: `${breakdown[p.key] * scale}%` }} title={`${p.label}: ${breakdown[p.key]} min`} />
        ))}
      </div>
      <p className="tabular mt-1.5 text-xs text-slate-500 dark:text-slate-400">
        {breakdown.travel_time} travel + {breakdown.predicted_wait} wait + {breakdown.charging_time} charge
        {breakdown.load_penalty > 0 && <> + {breakdown.load_penalty} load</>}
        {breakdown.urgency_bonus > 0 && <span className="font-semibold text-brand-700 dark:text-brand-400"> − {breakdown.urgency_bonus} urgency bonus</span>} ={" "}
        <span className="font-semibold text-slate-800 dark:text-slate-100">{breakdown.final_score}</span>
        <span className="sr-only"> (total cost terms {total.toFixed(1)})</span>
      </p>
    </div>
  );
}
