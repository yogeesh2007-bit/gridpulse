import { AlertTriangle, CheckCircle2, Crosshair, Loader2, MapPin, PenLine, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { GeoPosition, GeoStatus } from "../../hooks/useGeolocation";
import type { SyncState } from "../../hooks/useLocationSync";
import { cx, fmtAge } from "../../lib/format";
import type { GeoResult } from "../../lib/types";
import { Badge, type Tone } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Section } from "../ui/Card";
import { Field } from "../ui/Field";
import { Alert } from "../ui/Alert";

const STATUS: Record<GeoStatus, { label: string; tone: Tone; icon: typeof MapPin }> = {
  idle: { label: "Not shared", tone: "neutral", icon: MapPin },
  requesting: { label: "Locating…", tone: "info", icon: Loader2 },
  watching: { label: "Live", tone: "good", icon: CheckCircle2 },
  manual: { label: "Manual", tone: "info", icon: PenLine },
  denied: { label: "Permission denied", tone: "bad", icon: ShieldAlert },
  unavailable: { label: "Unavailable", tone: "warn", icon: AlertTriangle },
  timeout: { label: "Waiting for fix", tone: "warn", icon: AlertTriangle },
  insecure: { label: "Needs HTTPS", tone: "warn", icon: ShieldAlert },
  unsupported: { label: "Unsupported", tone: "bad", icon: AlertTriangle },
};

interface Props {
  status: GeoStatus;
  message: string;
  position: GeoPosition | null;
  place: GeoResult | null;
  placeLoading: boolean;
  sync: { state: SyncState; lastSentAt: number | null; error: string | null; active: boolean };
  defaultCenter: { lat: number; lon: number } | null;
  onStart: () => void;
  onManual: (lat: number, lon: number) => void;
}

export function LocationCard({ status, message, position, place, placeLoading, sync, defaultCenter, onStart, onManual }: Props) {
  const s = STATUS[status];
  const Icon = s.icon;
  const [showManual, setShowManual] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [manualError, setManualError] = useState<string | null>(null);

  const problem = status === "denied" || status === "unavailable" || status === "timeout" || status === "insecure" || status === "unsupported";
  const manualOpen = showManual || problem;

  const applyManual = () => {
    const la = Number(lat);
    const lo = Number(lon);
    if (lat.trim() === "" || lon.trim() === "" || !Number.isFinite(la) || !Number.isFinite(lo) || Math.abs(la) > 90 || Math.abs(lo) > 180) {
      setManualError("Enter a latitude between -90 and 90 and a longitude between -180 and 180.");
      return;
    }
    setManualError(null);
    onManual(la, lo);
  };

  return (
    <Section
      title="Your location"
      icon={<MapPin className="h-5 w-5" />}
      action={
        <Badge tone={s.tone}>
          <Icon className={cx("h-3.5 w-3.5", status === "requesting" && "animate-spin")} />
          {s.label}
        </Badge>
      }
    >
      <div className="space-y-3">
        {position ? (
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-ink-800">
            <p className="text-sm font-semibold text-slate-900 dark:text-white">
              {place ? place.short_name : placeLoading ? "Finding place name…" : "Position set"}
            </p>
            {place && place.source !== "fallback" && <p className="mt-0.5 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{place.name}</p>}
            <p className="tabular mt-1.5 font-mono text-xs text-slate-600 dark:text-slate-300" data-testid="coords">
              {position.lat.toFixed(5)}, {position.lon.toFixed(5)}
              {position.accuracy !== null && <span className="text-slate-400"> · ±{Math.round(position.accuracy)} m</span>}
            </p>
            {sync.active && (
              <p className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400" aria-live="polite">
                <span className={cx("h-1.5 w-1.5 rounded-full", sync.state === "error" ? "bg-red-500" : sync.state === "paused" ? "bg-slate-400" : "animate-pulseDot bg-brand-500")} />
                {sync.state === "error"
                  ? `Could not share position: ${sync.error}`
                  : sync.state === "paused"
                    ? "Sharing paused while this tab is in the background"
                    : sync.lastSentAt
                      ? `Sharing live position with the operator · updated ${fmtAge((Date.now() - sync.lastSentAt) / 1000)}`
                      : "Sharing live position with the operator…"}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-400">Share your live location so we can compute real route times to each station.</p>
        )}

        {problem && <Alert kind={status === "denied" ? "error" : "warning"}>{message}</Alert>}

        <div className="flex flex-wrap gap-2">
          <Button
            onClick={onStart}
            loading={status === "requesting"}
            icon={<Crosshair className="h-4 w-4" />}
            variant={status === "watching" ? "secondary" : "primary"}
            disabled={status === "watching"}
          >
            {status === "watching" ? "Tracking live" : status === "denied" ? "Try again" : "Use my location"}
          </Button>
          <Button variant="secondary" onClick={() => setShowManual((v) => !v)} icon={<PenLine className="h-4 w-4" />} aria-expanded={manualOpen}>
            Enter manually
          </Button>
        </div>

        {manualOpen && (
          <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-ink-700">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Latitude" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="13.0067" />
              <Field label="Longitude" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="80.0037" />
            </div>
            {manualError && <p className="text-xs text-red-600 dark:text-red-400">{manualError}</p>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={applyManual}>
                Use these coordinates
              </Button>
              {defaultCenter && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setLat(String(defaultCenter.lat));
                    setLon(String(defaultCenter.lon));
                    setManualError(null);
                    onManual(defaultCenter.lat, defaultCenter.lon);
                  }}
                >
                  Use demo area
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}
