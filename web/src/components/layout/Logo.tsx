import { Zap } from "lucide-react";
import { cx } from "../../lib/format";

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cx("inline-flex items-center gap-2.5", className)}>
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm">
        <Zap className="h-5 w-5" fill="currentColor" strokeWidth={1.5} />
      </span>
      {!compact && <span className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">GridPulse</span>}
    </span>
  );
}
