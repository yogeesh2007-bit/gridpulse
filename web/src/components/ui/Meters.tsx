import { cx } from "../../lib/format";

/** Site load vs limit: green < 70 %, amber < 90 %, red above (or over the limit). */
export function LoadBar({ pct, over, label, className }: { pct: number; over?: boolean; label?: string; className?: string }) {
  const value = Math.max(0, Math.min(100, pct));
  const color = over || pct >= 100 ? "bg-red-500" : pct >= 85 ? "bg-amber-500" : pct >= 70 ? "bg-yellow-400" : "bg-brand-500";
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      aria-label={label ?? "Site load"}
      className={cx("h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-ink-700", className)}
    >
      <div className={cx("h-full rounded-full transition-all duration-500", color)} style={{ width: `${value}%` }} />
    </div>
  );
}

export function PortDots({ total, busy }: { total: number; busy: number }) {
  return (
    <span className="inline-flex items-center gap-1" aria-label={`${total - busy} of ${total} ports free`}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={cx("h-3 w-3 rounded-full ring-1 ring-inset", i < busy ? "bg-amber-500 ring-amber-600" : "bg-brand-500 ring-brand-600")}
        />
      ))}
    </span>
  );
}

export function LiveDot({ on, className }: { on: boolean; className?: string }) {
  return (
    <span
      className={cx("inline-block h-2 w-2 rounded-full", on ? "animate-pulseDot bg-brand-500" : "bg-slate-400", className)}
      aria-hidden="true"
    />
  );
}
