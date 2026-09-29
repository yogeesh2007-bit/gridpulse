import { useEffect, useState } from "react";

export interface Health {
  status: string;
  openrouter_configured: boolean;
  routing_mode: string;
  demo_users: boolean;
  center: { lat: number; lon: number };
}

let cached: Health | null = null;

/** Public server info (used to decide whether to offer the optional AI rewrite, and the demo map centre). */
export function useHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(cached);
  useEffect(() => {
    if (cached) return;
    fetch("/health")
      .then((r) => (r.ok ? (r.json() as Promise<Health>) : null))
      .then((h) => {
        cached = h;
        setHealth(h);
      })
      .catch(() => undefined);
  }, []);
  return health;
}
