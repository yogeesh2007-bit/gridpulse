import { useCallback, useEffect, useRef, useState } from "react";

export type GeoStatus =
  | "idle" // not started
  | "requesting" // waiting for permission / first fix
  | "watching" // receiving live positions
  | "manual" // the user typed a position
  | "denied" // permission refused
  | "unavailable" // position could not be determined
  | "timeout" // no fix in time (still trying)
  | "insecure" // page is not https/localhost, browsers block geolocation
  | "unsupported"; // no geolocation API

export interface GeoPosition {
  lat: number;
  lon: number;
  accuracy: number | null;
  timestamp: number;
  source: "gps" | "manual";
}

const MESSAGES: Record<GeoStatus, string> = {
  idle: "Location is not shared yet.",
  requesting: "Waiting for your location…",
  watching: "Live location active.",
  manual: "Using the position you entered.",
  denied: "Location permission was denied. Allow it in your browser settings, or enter a position manually.",
  unavailable: "Your position is unavailable right now. Try again, or enter a position manually.",
  timeout: "Still waiting for a GPS fix… you can enter a position manually meanwhile.",
  insecure:
    "Browsers only share location on HTTPS or localhost. Open this app over HTTPS (e.g. a Cloudflare tunnel) or enter a position manually.",
  unsupported: "This browser cannot provide location. Enter a position manually.",
};

/** Live position via navigator.geolocation.watchPosition, with explicit status and a manual fallback. */
export function useGeolocation() {
  const [status, setStatus] = useState<GeoStatus>("idle");
  const [position, setPosition] = useState<GeoPosition | null>(null);
  const watchId = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (watchId.current !== null && "geolocation" in navigator) navigator.geolocation.clearWatch(watchId.current);
    watchId.current = null;
  }, []);

  const start = useCallback(() => {
    if (!("geolocation" in navigator)) return setStatus("unsupported");
    if (!window.isSecureContext) return setStatus("insecure");
    stop();
    setStatus("requesting");
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        setPosition({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy: pos.coords.accuracy ?? null,
          timestamp: pos.timestamp,
          source: "gps",
        });
        setStatus("watching");
      },
      (err) => {
        // PERMISSION_DENIED stops the watch for good; the others are transient and watchPosition keeps trying.
        setStatus(err.code === err.PERMISSION_DENIED ? "denied" : err.code === err.TIMEOUT ? "timeout" : "unavailable");
      },
      { enableHighAccuracy: true, maximumAge: 5_000, timeout: 20_000 },
    );
  }, [stop]);

  const setManual = useCallback(
    (lat: number, lon: number) => {
      stop();
      setPosition({ lat, lon, accuracy: null, timestamp: Date.now(), source: "manual" });
      setStatus("manual");
    },
    [stop],
  );

  useEffect(() => stop, [stop]); // stop watching when the component unmounts

  return { status, message: MESSAGES[status], position, start, stop, setManual };
}
