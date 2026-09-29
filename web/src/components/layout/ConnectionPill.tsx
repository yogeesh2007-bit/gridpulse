import { Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { cx } from "../../lib/format";
import { useLive } from "../../realtime/LiveContext";

const LABEL = { open: "Live", connecting: "Connecting…", reconnecting: "Reconnecting…", offline: "Offline" } as const;

/** WebSocket status + how fresh the last push is. */
export function ConnectionPill() {
  const { connection, lastUpdate } = useLive();
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  const live = connection === "open";
  const age = lastUpdate ? Math.max(0, Math.round((Date.now() - lastUpdate) / 1000)) : null;
  return (
    <span
      role="status"
      aria-live="polite"
      title={live && age !== null ? `Last update ${age}s ago` : LABEL[connection]}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        live
          ? "bg-brand-50 text-brand-800 ring-brand-200 dark:bg-brand-900/30 dark:text-brand-300 dark:ring-brand-800/60"
          : "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-900/25 dark:text-amber-300 dark:ring-amber-800/60",
      )}
    >
      {live ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
      <span>{LABEL[connection]}</span>
      {live && age !== null && <span className="tabular hidden font-normal opacity-70 sm:inline">· {age}s</span>}
    </span>
  );
}
