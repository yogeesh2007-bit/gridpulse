// Formatting helpers shared across the UI.

export const fmtMin = (m: number | null | undefined): string => {
  if (m === null || m === undefined || Number.isNaN(m)) return "–";
  const r = Math.round(m);
  if (r < 60) return `${r} min`;
  const h = Math.floor(r / 60);
  const rem = r % 60;
  return rem === 0 ? `${h} h` : `${h} h ${rem} min`;
};

export const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export const fmtKw = (w: number): string => `${(w / 1000).toFixed(w >= 100000 ? 0 : 1)} kW`;

export const fmtAge = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 2) return "just now";
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
};

export const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** Haversine distance in metres (for "did the driver move enough to send an update"). */
export function distanceMeters(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371008.8;
  const rad = Math.PI / 180;
  const dLat = (bLat - aLat) * rad;
  const dLon = (bLon - aLon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");
