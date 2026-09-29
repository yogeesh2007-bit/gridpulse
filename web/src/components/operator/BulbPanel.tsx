import { Lightbulb, LightbulbOff, Power, Radio, Signal } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { fmtAge, fmtTime } from "../../lib/format";
import type { BulbEvent, BulbView } from "../../lib/types";
import { Alert } from "../ui/Alert";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Section } from "../ui/Card";
import { LiveDot } from "../ui/Meters";
import { useToast } from "../ui/Toast";

const SOURCE: Record<string, string> = {
  manual_button_on: "Manual switch: light turned ON",
  manual_button_off: "Manual switch: light turned OFF",
  manual_button: "Manual switch",
  state_change: "Manual switch",
  remote_command: "Remote command from control room",
  boot: "Device boot",
  heartbeat: "Heartbeat",
  remote: "Control room command",
};

function BulbCard({ b }: { b: BulbView }) {
  const toast = useToast();
  const [busy, setBusy] = useState<boolean | null>(null);
  const [events, setEvents] = useState<BulbEvent[]>([]);
  const on = b.state === "on";

  useEffect(() => {
    let live = true;
    api<BulbEvent[]>(`/api/operator/bulbs/${b.device_id}/events`)
      .then((e) => live && setEvents(e))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [b.device_id, b.command_seq, b.last_state_change_at]);

  const send = async (target: boolean) => {
    setBusy(target);
    try {
      await api(`/api/operator/bulbs/${b.device_id}/command`, { json: { bulb_on: target } });
      toast.success(b.online ? `Sent: turn ${target ? "ON" : "OFF"}` : `Queued: turn ${target ? "ON" : "OFF"} (device is offline)`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Command failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section
      title={`Coach ${b.coach_id} · ${b.zone === "entrance_aisle" ? "Entrance light" : b.zone}`}
      subtitle={<span className="font-mono text-xs">{b.device_id}</span>}
      icon={on ? <Lightbulb className="h-5 w-5" /> : <LightbulbOff className="h-5 w-5" />}
      action={
        <Badge tone={b.online ? "good" : b.seen ? "warn" : "neutral"} dot>
          {b.online ? "Online" : b.seen ? "Offline" : "Never connected"}
        </Badge>
      }
    >
      <div data-testid="bulb-card" data-state={b.state} data-online={b.online} className="grid gap-5 sm:grid-cols-[auto_1fr]">
        <div className={`grid h-28 w-28 place-items-center rounded-3xl ${on ? "bg-amber-100 text-amber-500 shadow-[0_0_40px_-8px_rgba(245,158,11,.7)] dark:bg-amber-500/20" : "bg-slate-100 text-slate-400 dark:bg-ink-800"}`}>
          {on ? <Lightbulb className="h-14 w-14" fill="currentColor" /> : <LightbulbOff className="h-14 w-14" />}
        </div>
        <div className="space-y-3">
          <div>
            <p className="text-3xl font-extrabold tracking-tight text-slate-900 dark:text-white" data-testid="bulb-state">
              {b.state === "unknown" ? "No state yet" : on ? "Light ON" : "Light OFF"}
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {b.seen ? `Last seen ${fmtAge(b.age_s)}` : "Waiting for the device to connect"}
              {b.last_source && ` · ${SOURCE[b.last_source] ?? b.last_source}`}
            </p>
          </div>

          {b.sync === "pending" && (
            <Alert kind="info">
              Command sent, waiting for the device to confirm{b.online ? "…" : ". It is offline and will apply the command when it reconnects."}
            </Alert>
          )}
          {!b.online && b.seen && <Alert kind="warning">The device stopped reporting. The state shown is the last one it sent.</Alert>}

          <div className="flex flex-wrap gap-1.5" aria-label="Node status">
            <Badge tone={b.health === "healthy" ? "good" : b.health === "offline" ? "warn" : "neutral"}>Status: {b.health}</Badge>
            <Badge tone="info">{b.mode === "manual_override" ? "Manual switch" : b.mode === "remote_control" ? "Remote control" : b.mode}</Badge>
            <Badge>{b.voltage_type}</Badge>
            <Badge tone="good">LIVE hardware</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void send(true)} loading={busy === true} disabled={busy !== null || (on && b.sync === "in_sync")} icon={<Power className="h-4 w-4" />}>
              Turn ON
            </Button>
            <Button variant="secondary" onClick={() => void send(false)} loading={busy === false} disabled={busy !== null || (b.state === "off" && b.sync === "in_sync")} icon={<Power className="h-4 w-4" />}>
              Turn OFF
            </Button>
          </div>

          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><Signal className="h-3.5 w-3.5" />{b.rssi === null ? "no signal data" : `Wi-Fi ${b.rssi} dBm`}</span>
            {b.firmware && <span className="inline-flex items-center gap-1"><Radio className="h-3.5 w-3.5" />{b.firmware}</span>}
            {b.commanded_by && <span>Last set by {b.commanded_by}</span>}
          </p>
        </div>
      </div>

      <h4 className="mb-1.5 mt-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <LiveDot on={b.online} /> Activity
      </h4>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">No activity yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-ink-700">
          {events.slice(0, 8).map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 py-1.5">
              <span>
                <Badge tone={e.on ? "good" : "neutral"}>{e.on ? "ON" : "OFF"}</Badge>{" "}
                <span className="text-slate-700 dark:text-slate-200">{SOURCE[e.source ?? ""] ?? e.source}</span>
                {e.kind === "command" && e.detail && <span className="text-slate-500"> ({e.detail})</span>}
              </span>
              <span className="tabular text-xs text-slate-500">{fmtTime(e.ts)}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function BulbPanel({ bulbs }: { bulbs: BulbView[] }) {
  return (
    <div className="space-y-5" aria-label="Bulb nodes">
      {bulbs.map((b) => (
        <BulbCard key={b.device_id} b={b} />
      ))}
    </div>
  );
}
