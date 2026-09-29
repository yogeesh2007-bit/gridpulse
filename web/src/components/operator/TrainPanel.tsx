import { Lightbulb, LightbulbOff, TrainFront } from "lucide-react";
import { fmtAge } from "../../lib/format";
import type { TrainView } from "../../lib/types";
import { Badge } from "../ui/Badge";
import { Section } from "../ui/Card";

const MODE: Record<string, string> = { manual_override: "Manual switch", remote_control: "Remote control", boot: "Just started", idle: "Idle" };

/** Coach overview. The coach light node is LIVE hardware; every other item is seeded sample data and labelled so. */
export function TrainPanel({ train }: { train: TrainView }) {
  return (
    <Section title={`${train.name} · ${train.coach.name}`} subtitle="Lighting points and coach systems" icon={<TrainFront className="h-5 w-5" />}>
      <ul className="divide-y divide-slate-100 dark:divide-ink-700" aria-label="Lighting points">
        {train.light_points.map((p) => {
          const on = p.state === "on";
          return (
            <li key={p.device_id} data-testid="light-point" data-live={p.live} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <span className="flex items-center gap-2.5">
                {on ? <Lightbulb className="h-5 w-5 text-amber-500" fill="currentColor" /> : <LightbulbOff className="h-5 w-5 text-slate-400" />}
                <span>
                  <span className="block text-sm font-semibold text-slate-900 dark:text-white">{p.label}</span>
                  <span className="block text-xs text-slate-500">
                    {p.live
                      ? `${MODE[p.mode ?? "idle"] ?? p.mode} · ${p.health}${p.last_seen_at ? ` · updated ${fmtAge((Date.now() - new Date(p.last_seen_at).getTime()) / 1000)}` : ""}`
                      : `Zone: ${p.zone}`}
                  </span>
                </span>
              </span>
              <span className="flex items-center gap-1.5">
                <Badge tone={on ? "good" : "neutral"}>{p.state === "unknown" ? "No state yet" : on ? "Light ON" : "Light OFF"}</Badge>
                {p.live ? <Badge tone={p.online ? "good" : "warn"} dot>LIVE{p.online ? "" : " · offline"}</Badge> : <Badge>Seeded</Badge>}
              </span>
            </li>
          );
        })}
      </ul>
      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Coach systems</h4>
      <ul className="grid gap-2 sm:grid-cols-3">
        {train.systems.map((s) => (
          <li key={s.id} className="rounded-xl bg-slate-50 p-2.5 text-sm dark:bg-ink-800">
            <span className="font-medium text-slate-800 dark:text-slate-100">{s.label}</span>
            <span className="block text-xs capitalize text-slate-500">{s.status}</span>
            <Badge className="mt-1">Seeded</Badge>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-500">{train.note}</p>
    </Section>
  );
}
