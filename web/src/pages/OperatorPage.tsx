import { Activity, BatteryCharging, Cpu, LayoutDashboard, ListChecks, Radio, TimerReset, Users, Zap } from "lucide-react";
import { useState } from "react";
import { DecisionPanel } from "../components/operator/DecisionPanel";
import { TrainPanel } from "../components/operator/TrainPanel";
import { HardwarePanel } from "../components/operator/HardwarePanel";
import { QueueBoard, Timeline } from "../components/operator/QueueBoard";
import { ReservationsTable } from "../components/operator/ReservationsTable";
import { StationStatusCard } from "../components/operator/StationStatusCard";
import { AppShell, useTab, type NavItem } from "../components/layout/AppShell";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState, Section, Stat } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { api } from "../lib/api";
import { fmtAge } from "../lib/format";
import { useLive } from "../realtime/LiveContext";

const TITLES: Record<string, [string, string]> = {
  overview: ["Operations overview", "Live stations, load and the latest decision"],
  stations: ["Stations", "Site power limits and grid controls"],
  reservations: ["Reservations", "Every booking across all drivers"],
  queue: ["Queue & schedule", "Who is charging and who is next"],
  hardware: ["Hardware control", "Commands, devices and telemetry"],
};

export default function OperatorPage() {
  const { operatorState: s, connection } = useLive();
  const toast = useToast();
  const [resetting, setResetting] = useState(false);
  const urgentWaiting = s ? s.reservations.filter((r) => r.priority_class === "urgent" && r.status === "queued").length : 0;

  const items: NavItem[] = [
    { key: "overview", label: "Overview", icon: LayoutDashboard },
    { key: "stations", label: "Stations", icon: BatteryCharging },
    { key: "reservations", label: "Reservations", icon: ListChecks, badge: urgentWaiting || undefined },
    { key: "queue", label: "Queue", icon: Users },
    { key: "hardware", label: "Hardware", icon: Cpu },
  ];
  const [tab] = useTab(items);
  const [title, subtitle] = TITLES[tab];

  const reset = async () => {
    if (!window.confirm("Reset stations, queue, requests and telemetry to the demo scenario? Accounts are kept.")) return;
    setResetting(true);
    try {
      await api("/api/operator/seed", { method: "POST" });
      toast.success("Demo data reset");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  };

  return (
    <AppShell basePath="/app/operator" items={items} title={title} subtitle={subtitle}>
      {!s ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading live state">
          {connection !== "open" && (
            <Alert kind="info" title={connection === "offline" ? "Offline" : "Connecting to live updates…"}>
              The dashboard fills in as soon as the live connection is up.
            </Alert>
          )}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
          <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
        </div>
      ) : (
        <div className="space-y-5">
          {connection !== "open" && <Alert kind="warning" title="Live connection lost">Showing the last known state. Reconnecting…</Alert>}

          {tab === "overview" && (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <Stat label="Stations online" value={`${s.totals.stations_online}/${s.totals.stations}`} tone={s.totals.stations_online === s.totals.stations ? "good" : "warn"} icon={<Radio className="h-4 w-4" />} />
                <Stat label="Active sessions" value={s.totals.active_sessions} icon={<Zap className="h-4 w-4" />} />
                <Stat label="Queued" value={s.totals.queued} icon={<Users className="h-4 w-4" />} />
                <Stat label="EV load" value={`${s.totals.ev_load_kw} kW`} icon={<Activity className="h-4 w-4" />} />
                <Stat label="Urgent waiting" value={urgentWaiting} tone={urgentWaiting ? "bad" : "default"} icon={<TimerReset className="h-4 w-4" />} hint={s.hardware_summary.mode === "real" ? "real hardware live" : s.hardware_summary.mode === "simulated" ? "simulated device" : "software-simulated"} />
              </div>
              {s.train && <TrainPanel train={s.train} />}
              <div className="grid gap-5 xl:grid-cols-2">{s.stations.map((st) => <StationStatusCard key={st.id} station={st} />)}</div>
              <DecisionPanel rec={s.latest_recommendation} />
              <Section title="Live driver locations" subtitle="Positions shared by drivers with an open request" icon={<Radio className="h-5 w-5" />}>
                {s.live_drivers.length === 0 ? (
                  <p className="text-sm text-slate-500">No driver has shared a live location recently.</p>
                ) : (
                  <ul className="divide-y divide-slate-100 dark:divide-ink-700">
                    {s.live_drivers.map((d) => (
                      <li key={d.request_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                        <span className="flex items-center gap-2"><Badge tone={d.is_live ? "good" : "neutral"} dot>{d.is_live ? "live" : "idle"}</Badge><b>{d.driver_name}</b></span>
                        <span className="tabular font-mono text-xs text-slate-500">{d.lat.toFixed(4)}, {d.lon.toFixed(4)} · {fmtAge(d.age_s)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}

          {tab === "stations" && (
            <>
              <div className="grid gap-5 xl:grid-cols-2">{s.stations.map((st) => <StationStatusCard key={st.id} station={st} controls />)}</div>
              <Section title="Demo data" subtitle="Restore the starting scenario">
                <Button variant="danger" onClick={() => void reset()} loading={resetting}>Reset demo data</Button>
              </Section>
            </>
          )}

          {tab === "reservations" && (
            s.reservations.length === 0 && s.recent_finished.length === 0
              ? <EmptyState icon={<ListChecks className="h-10 w-10" />} title="No reservations">Bookings from all drivers will appear here live.</EmptyState>
              : <ReservationsTable open={s.reservations} finished={s.recent_finished} />
          )}

          {tab === "queue" && <QueueBoard state={s} />}
          {tab === "hardware" && <HardwarePanel state={s} />}
          {tab === "overview" && <Timeline state={s} />}
        </div>
      )}
    </AppShell>
  );
}
