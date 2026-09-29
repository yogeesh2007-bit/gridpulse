import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { distanceMeters } from "../lib/format";
import type { GeoResult } from "../lib/types";
import type { GeoPosition } from "./useGeolocation";

const DEBOUNCE_MS = 700;
const MIN_MOVE_M = 60; // do not re-geocode for small movements

/** A readable place name for a position (backend caches Nominatim). Falls back to coordinates silently. */
export function usePlaceName(position: GeoPosition | null) {
  const [place, setPlace] = useState<GeoResult | null>(null);
  const [loading, setLoading] = useState(false);
  const resolved = useRef<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    if (!position) {
      setPlace(null);
      resolved.current = null;
      return;
    }
    const prev = resolved.current;
    if (prev && distanceMeters(prev.lat, prev.lon, position.lat, position.lon) < MIN_MOVE_M) return;

    const ctrl = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api<GeoResult>(`/api/geo/reverse?lat=${position.lat}&lon=${position.lon}`, { signal: ctrl.signal });
        resolved.current = { lat: position.lat, lon: position.lon };
        setPlace(res);
      } catch {
        /* cosmetic: keep whatever we had */
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [position]);

  return { place, loading };
}
