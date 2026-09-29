import { Bot, Trophy } from "lucide-react";
import { cx, fmtKw, fmtMin } from "../../lib/format";
import type { OperatorState } from "../../lib/types";
import { Badge, PriorityBadge } from "../ui/Badge";
import { EmptyState, Section } from "../ui/Card";

/** The latest recommendation: who asked, which station won, the full ranking with every score term, and why. */
export function DecisionPanel({ rec }: { rec: OperatorState["latest_recommendation"] }) {
  if (!rec) {
    return (
      <Section title="Latest recommendation" icon={<Trophy className="h-5 w-5" />}>
        <EmptyState title="No recommendation yet">When a driver asks for a charger, the decision and its reasoning appear here live.</EmptyState>
      </Section>
    );
  }
  const d = rec.driver;
  return (
    <Section
      title="Latest recommendation"
      icon={<Trophy className="h-5 w-5" />}
      subtitle={<>{d.name} · {d.soc_current}% → {d.soc_target}% · deadline {fmtMin(d.deadline_minutes)} · <PriorityBadge priority={d.priority_class} /></>}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Chosen station</p>
      <p className="text-xl font-bold text-slate-900 dark:text-white" data-testid="chosen-station">{rec.chosen_station?.name ?? "No usable station"}</p>

      <div className="card mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-ink-700">
            <tr>{["#", "Station", "Ports free", "Queue", "Load / limit", "Travel", "Wait", "Charge", "Load pen.", "Urgency bonus", "Final"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rec.ranking.map((r) => {
              const b = r.score_breakdown;
              const best = rec.chosen_station?.id === r.station_id;
              return (
                <tr key={r.station_id} className={cx("border-b border-slate-100 last:border-0 dark:border-ink-700", best && "bg-brand-50/60 dark:bg-brand-900/15")}>
                  <td className="px-3 py-2">{r.rank}</td>
                  <td className="px-3 py-2 font-semibold">{r.name} {best && <Badge tone="good">chosen</Badge>}</td>
                  <td className="tabular px-3 py-2">{r.station_state.available_ports}</td>
                  <td className="tabular px-3 py-2">{r.station_state.queue_count}</td>
                  <td className="tabular px-3 py-2">{fmtKw(r.station_state.current_load_w)} / {fmtKw(r.station_state.site_power_limit_w)}</td>
                  {b ? (
                    <>
                      <td className="tabular px-3 py-2">{b.travel_time}</td>
                      <td className="tabular px-3 py-2">{b.predicted_wait}</td>
                      <td className="tabular px-3 py-2">{b.charging_time}</td>
                      <td className="tabular px-3 py-2 text-amber-600">+{b.load_penalty}</td>
                      <td className="tabular px-3 py-2 text-brand-700 dark:text-brand-400">−{b.urgency_bonus}</td>
                      <td className="tabular px-3 py-2 font-bold">{b.final_score}</td>
                    </>
                  ) : (
                    <td colSpan={6} className="px-3 py-2 text-slate-500">Not usable: {r.rejection_reason}</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{rec.formula} (minutes, lower is better)</p>
      {rec.warnings.map((w) => <p key={w} className="mt-2 text-sm text-amber-700 dark:text-amber-300">{w}</p>)}
      <div className="mt-3 rounded-xl border-l-4 border-brand-500 bg-slate-50 p-3 dark:bg-ink-800">
        <p className="text-sm text-slate-800 dark:text-slate-200"><b>Why:</b> {rec.explanation.text}</p>
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-500">
          {rec.explanation.source === "llm" ? <><Bot className="h-3.5 w-3.5" /> Reworded by AI. The ranking above is deterministic.</> : "Rule-based explanation from the deterministic engine."}
        </p>
      </div>
    </Section>
  );
}
