import { CalendarCheck, MapPinned, RefreshCw, SearchX, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell, useTab, type NavItem } from "../components/layout/AppShell";
import { DEFAULT_NEED, NeedForm, type NeedValues } from "../components/driver/NeedForm";
import { ExplanationPanel } from "../components/driver/ExplanationPanel";
import { LocationCard } from "../components/driver/LocationCard";
import { ReservationCard } from "../components/driver/ReservationCard";
import { StationRankCard } from "../components/driver/StationRankCard";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/Card";
import { Skeleton } from "../components/ui/Spinner";
import { useToast } from "../components/ui/Toast";
import { useGeolocation } from "../hooks/useGeolocation";
import { useHealth } from "../hooks/useHealth";
import { useLocationSync } from "../hooks/useLocationSync";
import { usePlaceName } from "../hooks/usePlaceName";
import { api } from "../lib/api";
import { fmtMin, fmtTime } from "../lib/format";
import type { ExplanationResult, LatestRequest, Recommendation, Reservation } from "../lib/types";
import { useLive } from "../realtime/LiveContext";

const isOpen = (r: Reservation) => r.status === "queued" || r.status === "active";
const AUTO_REFRESH_MS = 30_000;

export default function DriverPage() {
  const toast = useToast();
  const health = useHealth();
  const { driverSnapshot } = useLive();
  const geo = useGeolocation();
  const { place, loading: placeLoading } = usePlaceName(geo.position);

  const [need, setNeed] = useState<NeedValues>(DEFAULT_NEED);
  const [requestId, setRequestId] = useState<number | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [reservingId, setReservingId] = useState<number | null>(null);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [localReservations, setLocalReservations] = useState<Reservation[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiNote, setAiNote] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const sync = useLocationSync(requestId, geo.position);

  // live data pushed over the WebSocket wins over what we fetched
  const reservations = driverSnapshot?.reservations ?? localReservations;
  const open = reservations.filter(isOpen);
  const liveStations = useMemo(() => new Map((driverSnapshot?.stations ?? []).map((s) => [s.id, s])), [driverSnapshot]);

  const items: NavItem[] = [
    { key: "plan", label: "Find charger", icon: Zap },
    { key: "reservations", label: "Reservations", icon: CalendarCheck, badge: open.length || undefined },
  ];
  const [tab, setTab] = useTab(items);

  // ---- restore the last session (page reload) ----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [latest, mine] = await Promise.all([
          api<LatestRequest>("/api/driver/requests/latest"),
          api<Reservation[]>("/api/driver/reservations"),
        ]);
        if (cancelled) return;
        setLocalReservations(mine);
        if (latest.request) {
          setRequestId(latest.request.id);
          setNeed({
            soc: latest.request.soc_current,
            target: latest.request.soc_target,
            deadline: Math.round(latest.request.deadline_minutes),
            batteryKwh: latest.request.battery_kwh,
            maxKw: latest.request.max_charge_kw,
          });
          setRec(latest.recommendation);
        }
      } catch {
        /* first visit or offline: start with an empty form */
      } finally {
        if (!cancelled) setRestoring(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ---- actions ------------------------------------------------------------------------------------------
  const submit = useCallback(async () => {
    const pos = geo.position;
    if (!pos) return;
    setLoading(true);
    setError(null);
    setAiNote(null);
    try {
      const result = await api<Recommendation>("/api/driver/recommend", {
        json: {
          lat: pos.lat,
          lng: pos.lon,
          soc: need.soc,
          target_soc: need.target,
          deadline: need.deadline,
          battery_kwh: need.batteryKwh,
          max_charge_kw: need.maxKw,
          location_source: pos.source,
          location_accuracy_m: pos.accuracy,
        },
      });
      setRec(result);
      setRequestId(result.request_id);
      window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not get a recommendation");
    } finally {
      setLoading(false);
    }
  }, [geo.position, need]);

  const refresh = useCallback(
    async (quiet = false) => {
      if (requestId === null) return;
      setRefreshing(true);
      try {
        await sync.sendNow(); // make sure the backend has the newest position first
        const result = await api<Recommendation>(`/api/driver/requests/${requestId}/refresh`, { method: "POST" });
        setRec((prev) => {
          if (!quiet && prev?.chosen_station && result.chosen_station && prev.chosen_station.id !== result.chosen_station.id) {
            toast.success(`Best station changed to ${result.chosen_station.name}`);
          }
          return result;
        });
        setAiNote(null);
      } catch (e) {
        if (!quiet) toast.error(e instanceof Error ? e.message : "Could not refresh");
      } finally {
        setRefreshing(false);
      }
    },
    [requestId, sync, toast],
  );

  // optional auto-refresh while driving (only until they have reserved)
  useEffect(() => {
    if (!autoRefresh || requestId === null || open.length > 0) return;
    const t = window.setInterval(() => !document.hidden && void refresh(true), AUTO_REFRESH_MS);
    return () => window.clearInterval(t);
  }, [autoRefresh, requestId, open.length, refresh]);

  const reserve = async (stationId: number) => {
    if (requestId === null) return;
    setReservingId(stationId);
    try {
      const res = await api<Reservation>("/api/driver/reservations", { json: { request_id: requestId, station_id: stationId } });
      setLocalReservations((prev) => [res, ...prev.filter((r) => r.id !== res.id)]);
      toast.success(`Reserved at ${res.station_name}`);
      setAutoRefresh(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not reserve");
    } finally {
      setReservingId(null);
    }
  };

  const cancel = async (id: number) => {
    setCancellingId(id);
    try {
      const res = await api<Reservation>(`/api/driver/reservations/${id}/cancel`, { method: "POST" });
      setLocalReservations((prev) => prev.map((r) => (r.id === id ? res : r)));
      toast.success("Reservation cancelled");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not cancel");
    } finally {
      setCancellingId(null);
    }
  };

  const rewrite = async () => {
    if (requestId === null) return;
    setAiLoading(true);
    setAiNote(null);
    try {
      const out = await api<ExplanationResult>("/api/explain", { json: { request_id: requestId } });
      setRec((prev) => (prev ? { ...prev, explanation: { text: out.text, source: out.source, model: out.model } } : prev));
      if (out.source === "rules") setAiNote("The AI service was unavailable right now, so this is the standard explanation. You can try again.");
    } catch (e) {
      setAiNote(e instanceof Error ? e.message : "Could not reach the explanation service");
    } finally {
      setAiLoading(false);
    }
  };

  // ---- derived view data ----------------------------------------------------------------------------------
  const ranking = rec?.ranking ?? [];
  const maxScore = Math.max(1, ...ranking.map((r) => r.score_breakdown?.travel_time ? r.score_breakdown.travel_time + r.score_breakdown.predicted_wait + r.score_breakdown.charging_time + r.score_breakdown.load_penalty : 0));
  const hasOpen = open.length > 0;
  const chosenEta = sync.etas.find((e) => e.station_id === rec?.chosen_station?.id);

  return (
    <AppShell basePath="/app/driver" items={items} title={tab === "plan" ? "Find a charger" : "My reservations"} subtitle={tab === "plan" ? "Ranked by earliest safe completion" : "Live status of your bookings"}>
      {tab === "reservations" ? (
        <div className="space-y-4">
          {reservations.length === 0 ? (
            <EmptyState icon={<CalendarCheck className="h-10 w-10" />} title="No reservations yet">
              Find a charger and reserve it. Your bookings will appear here and update live.
              <span className="mt-4 block">
                <Button onClick={() => setTab("plan")}>Find a charger</Button>
              </span>
            </EmptyState>
          ) : (
            <>
              {reservations.map((r) => (
                <ReservationCard key={r.id} r={r} onCancel={cancel} cancelling={cancellingId === r.id} />
              ))}
            </>
          )}
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="space-y-5">
            <LocationCard
              status={geo.status}
              message={geo.message}
              position={geo.position}
              place={place}
              placeLoading={placeLoading}
              sync={{ state: sync.state, lastSentAt: sync.lastSentAt, error: sync.error, active: requestId !== null }}
              defaultCenter={health?.center ?? null}
              onStart={geo.start}
              onManual={geo.setManual}
            />
            <NeedForm
              values={need}
              onChange={setNeed}
              onSubmit={submit}
              loading={loading}
              hasPosition={!!geo.position}
              submitLabel={rec ? "Update recommendation" : "Find best charger"}
            />
          </div>

          <div ref={resultsRef} className="scroll-mt-24 space-y-5" aria-live="polite">
            {hasOpen && (
              <div className="space-y-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Your reservation</h2>
                {open.map((r) => (
                  <ReservationCard key={r.id} r={r} onCancel={cancel} cancelling={cancellingId === r.id} />
                ))}
              </div>
            )}

            {error && (
              <Alert kind="error" title="We could not get a recommendation">
                {error}
              </Alert>
            )}

            {loading || restoring ? (
              <div className="space-y-4" aria-busy="true" aria-label="Loading recommendation">
                <Skeleton className="h-28" />
                <Skeleton className="h-64" />
                <Skeleton className="h-64" />
              </div>
            ) : rec ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900 dark:text-white">Recommendation</h2>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Updated {fmtTime(rec.generated_at)} · {rec.driver.soc_current}% → {rec.driver.soc_target}% · deadline {fmtMin(rec.driver.deadline_minutes)}
                      {rec.driver.priority_class === "urgent" && (
                        <>
                          {" "}
                          <Badge tone="urgent">urgent</Badge>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-600 dark:text-slate-300">
                      <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} disabled={hasOpen} className="h-4 w-4 accent-brand-600" />
                      Auto-refresh (30 s)
                    </label>
                    <Button variant="secondary" size="sm" onClick={() => void refresh()} loading={refreshing} icon={<RefreshCw className="h-4 w-4" />}>
                      Refresh
                    </Button>
                  </div>
                </div>

                {rec.warnings.map((w) => (
                  <Alert key={w} kind="warning">
                    {w}
                  </Alert>
                ))}

                {sync.etas.length > 0 && (
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-brand-200 bg-brand-50 px-3.5 py-2.5 text-sm text-brand-900 dark:border-brand-800/60 dark:bg-brand-900/20 dark:text-brand-200">
                    <span className="inline-flex items-center gap-1.5 font-semibold">
                      <MapPinned className="h-4 w-4" /> Live ETA
                    </span>
                    {sync.etas.map((e) => (
                      <span key={e.station_id} className={e.station_id === chosenEta?.station_id ? "font-bold" : ""}>
                        {e.station_code}: {fmtMin(e.travel_min)} ({e.distance_km.toFixed(1)} km)
                      </span>
                    ))}
                    {sync.routingFallback && <Badge tone="warn">estimated</Badge>}
                  </div>
                )}

                {rec.chosen_station ? (
                  <ExplanationPanel explanation={rec.explanation} aiAvailable={!!health?.openrouter_configured} aiLoading={aiLoading} aiNote={aiNote} onRewrite={rewrite} />
                ) : (
                  <Alert kind="error" title="No usable station right now">
                    {rec.explanation.text}
                  </Alert>
                )}

                <div className="space-y-4">
                  {ranking.map((entry) => (
                    <StationRankCard
                      key={entry.station_id}
                      entry={entry}
                      best={rec.chosen_station?.id === entry.station_id}
                      maxScore={maxScore}
                      live={liveStations.get(entry.station_id)}
                      estimated={rec.routing.estimated}
                      disabled={hasOpen}
                      reserving={reservingId === entry.station_id}
                      onReserve={reserve}
                    />
                  ))}
                </div>
                {rec.routing.note && <p className="text-xs text-slate-500 dark:text-slate-400">{rec.routing.note}</p>}
              </>
            ) : (
              <EmptyState icon={<SearchX className="h-10 w-10" />} title="No recommendation yet">
                Share your location, set your charge and deadline, and we will rank every station by how soon it can finish charging you.
              </EmptyState>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}
