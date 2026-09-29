import { Cpu, FlaskConical, Lock } from "lucide-react";
import { fmtAge, fmtTime } from "../../lib/format";
import type { ControlView, DeviceView, OperatorState } from "../../lib/types";
import { Alert } from "../ui/Alert";
import { Badge, type Tone } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Section } from "../ui/Card";

const CMD_TONE: Record<string, Tone> = { NORMAL: "good", REDUCE_LOAD: "warn", PRIORITIZE_URGENT: "urgent", PAUSE_FLEX: "bad" };
const COMMANDS = ["NORMAL", "REDUCE_LOAD", "PRIORITIZE_URGENT", "PAUSE_FLEX"];

function confirmation(c: ControlView): { tone: Tone; label: string } {
  if (c.confirmation === "hardware-confirmed") return { tone: "good", label: `Hardware confirmed${c.dry_run ? " · dry-run" : ""}` };
  if (c.confirmation === "hardware-pending") return { tone: "warn", label: "Hardware pending" };
  if (c.device_mode === "real") return { tone: "bad", label: c.telemetry_age_s == null ? "Awaiting hardware → simulated" : `Hardware ${c.freshness} → simulated` };
  if (c.device_mode === "simulated") return { tone: "info", label: "Simulated device" };
  return { tone: "neutral", label: "Software-simulated" };
}

const freshTone = (f: string): Tone => (f === "live" ? "good" : f === "stale" ? "warn" : "bad");

function DeviceCard({ d }: { d: DeviceView }) {
  return (
    <div className="rounded-xl border border-slate-200 p-3 text-sm dark:border-ink-700">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-xs font-semibold">{d.device_id}</span>
        <Badge tone={d.device_mode === "real" ? "good" : "info"}>{d.device_mode}</Badge>
        <Badge tone={freshTone(d.freshness)} dot>{d.freshness}</Badge>
        {d.placeholder && <Badge>placeholder</Badge>}
        {d.dry_run && <Badge tone="warn">dry-run</Badge>}
        {d.sensor_status !== "ok" && d.sensor_status !== "unknown" && <Badge tone="bad">sensor {d.sensor_status}</Badge>}
        {d.local_override && <Badge tone="urgent">local override</Badge>}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
        <dt className="text-slate-500">Last telemetry</dt><dd>{d.last_telemetry_at ? `${fmtTime(d.last_telemetry_at)} (${fmtAge(d.telemetry_age_s)})` : "never"}</dd>
        <dt className="text-slate-500">Command sent</dt><dd>{d.last_command_sent ? `${d.last_command_sent.command} #${d.last_command_sent.seq}` : "none yet"}</dd>
        <dt className="text-slate-500">Acknowledgment</dt><dd>{d.ack_status}{d.last_ack ? ` · ${d.last_ack.status} #${d.last_ack.seq}` : ""}</dd>
        <dt className="text-slate-500">Button presses</dt><dd>{d.button_count}</dd>
      </dl>
      {d.caveats.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs text-amber-700 dark:text-amber-300">{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>}
      {d.fallback_reason && <p className="mt-2 text-xs text-slate-500"><b>Fallback:</b> {d.fallback_reason}</p>}
    </div>
  );
}

export function HardwarePanel({ state }: { state: OperatorState }) {
  const hw = state.hardware_summary;
  return (
    <div className="space-y-5">
      <Alert kind={hw.mode === "real" ? "success" : "info"} title={hw.mode === "real" ? "Real hardware is live" : hw.mode === "simulated" ? "A simulated device is live" : "No live device: control is simulated by the backend"}>
        {hw.mode === "real"
          ? "Commands below are confirmed by the ESP32 (check the dry-run flag before assuming a physical output)."
          : "Commands are computed and logged, but no physical output is switched. The ESP32 + INA219 + MOSFET path plugs in through the same device protocol."}
      </Alert>

      <div className="grid gap-5 lg:grid-cols-2">
        {state.stations.map((s) => {
          const c = s.control;
          if (!c) return null;
          const conf = confirmation(c);
          return (
            <Section key={s.id} title={`${s.name} — control`} icon={<Cpu className="h-5 w-5" />} action={<Badge tone={conf.tone}>{conf.label}</Badge>}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={CMD_TONE[c.command]}>{c.command}</Badge>
                <span className="tabular text-sm text-slate-600 dark:text-slate-300">output {c.duty_pct}% · command #{c.seq}</span>
              </div>
              <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">{c.reason}</p>
              {c.fallback_reason && <p className="mt-1.5 text-xs text-slate-500"><b>Fallback:</b> {c.fallback_reason}</p>}

              {s.telemetry && (
                <div className="mt-3 grid grid-cols-4 gap-2 text-center">
                  {[["Voltage", `${s.telemetry.voltage.toFixed(2)} V`], ["Current", `${s.telemetry.current.toFixed(3)} A`], ["Power", `${s.telemetry.power.toFixed(2)} W`], ["Temp", s.telemetry.temperature == null ? "–" : `${s.telemetry.temperature.toFixed(1)} °C`]].map(([k, v]) => (
                    <div key={k} className={`rounded-lg bg-slate-50 p-2 dark:bg-ink-800 ${s.telemetry?.sensor_status === "missing" ? "opacity-50" : ""}`}>
                      <div className="text-[10px] font-semibold uppercase text-slate-500">{k}</div>
                      <div className="tabular text-sm font-bold">{s.telemetry?.sensor_status === "missing" ? "–" : v}</div>
                    </div>
                  ))}
                </div>
              )}
              {s.device ? <div className="mt-3"><DeviceCard d={s.device} /></div> : <p className="mt-3 text-xs text-slate-500">Software-only station: no device assigned.</p>}

              {/* Placeholder: manual override arrives with the ESP32/MOSFET hardware. Deliberately disabled. */}
              <div className="mt-4 rounded-xl border border-dashed border-slate-300 p-3 dark:border-ink-600" aria-label="Manual override (placeholder)">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500"><Lock className="h-3.5 w-3.5" /> Manual override <Badge>placeholder</Badge></p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COMMANDS.map((cmd) => <Button key={cmd} size="sm" variant="secondary" disabled title="Available once ESP32/MOSFET hardware is connected">{cmd.replace("_", " ")}</Button>)}
                </div>
                <p className="mt-2 text-xs text-slate-500">Disabled: commands are derived automatically from load, queue and urgency. Manual overrides need real hardware to act on.</p>
              </div>
            </Section>
          );
        })}
      </div>

      <Section title="Decision log" icon={<FlaskConical className="h-5 w-5" />} subtitle="Every control command change, newest first">
        {state.control_events.length === 0 ? (
          <p className="text-sm text-slate-500">No decisions yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-ink-700">
            {state.control_events.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                <span className="tabular text-xs text-slate-500">{fmtTime(e.ts)}</span>
                <Badge>{e.station_code}</Badge>
                <span className="text-xs text-slate-500">{e.previous ?? "—"} →</span>
                <Badge tone={CMD_TONE[e.command] ?? "neutral"}>{e.command}</Badge>
                <span className="min-w-0 flex-1 text-xs text-slate-600 dark:text-slate-300">{e.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
