import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { distanceMeters } from "../lib/format";
import type { LiveEta, LocationUpdateResult } from "../lib/types";
import type { GeoPosition } from "./useGeolocation";

const MIN_MOVE_M = 20; // send when the driver moved at least this far...
const HEARTBEAT_MS = 15_000; // ...or at least this often while the tab is visible

export type SyncState = "idle" | "sending" | "ok" | "error" | "paused";

/** Pushes the live position to the backend for a request and keeps the latest route ETAs. */
export function useLocationSync(requestId: number | null, position: GeoPosition | null) {
  const [state, setState] = useState<SyncState>("idle");
  const [etas, setEtas] = useState<LiveEta[]>([]);
  const [routingFallback, setRoutingFallback] = useState(false);
  const [lastSentAt, setLastSentAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const last = useRef<{ lat: number; lon: number; at: number } | null>(null);
  const sending = useRef(false);
  const latest = useRef({ requestId, position });
  latest.current = { requestId, position };

  const push = useCallback(async (force: boolean) => {
    const { requestId: id, position: pos } = latest.current;
    if (id === null || !pos || sending.current) return;
    if (document.hidden && !force) return setState("paused");
    const prev = last.current;
    const moved = prev ? distanceMeters(prev.lat, prev.lon, pos.lat, pos.lon) : Infinity;
    if (!force && prev && moved < MIN_MOVE_M && Date.now() - prev.at < HEARTBEAT_MS) return;

    sending.current = true;
    setState("sending");
    try {
      const out = await api<LocationUpdateResult>("/api/driver/location", {
        json: { request_id: id, lat: pos.lat, lon: pos.lon, accuracy_m: pos.accuracy, source: pos.source },
      });
      last.current = { lat: pos.lat, lon: pos.lon, at: Date.now() };
      setEtas(out.etas);
      setRoutingFallback(out.routing_fallback_used);
      setLastSentAt(Date.now());
      setError(null);
      setState("ok");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send location");
      setState("error");
    } finally {
      sending.current = false;
    }
  }, []);

  // a new request starts a fresh sync immediately
  useEffect(() => {
    last.current = null;
    setEtas([]);
    setLastSentAt(null);
    if (requestId !== null && position) void push(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);

  // send on movement, and check on a heartbeat
  useEffect(() => {
    void push(false);
  }, [position, push]);
  useEffect(() => {
    const t = window.setInterval(() => void push(false), 5_000);
    const onVisible = () => !document.hidden && void push(true);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [push]);

  return { state, etas, routingFallback, lastSentAt, error, sendNow: () => push(true) };
}
