import type { ReactNode } from "react";
import { cx } from "../../lib/format";
import type { PriorityClass } from "../../lib/types";

export type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "urgent";

const TONES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-ink-700 dark:text-slate-200 dark:ring-ink-600",
  good: "bg-brand-50 text-brand-800 ring-brand-200 dark:bg-brand-900/30 dark:text-brand-300 dark:ring-brand-800/60",
  warn: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-900/25 dark:text-amber-300 dark:ring-amber-800/60",
  bad: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-900/25 dark:text-red-300 dark:ring-red-800/60",
  info: "bg-sky-50 text-sky-800 ring-sky-200 dark:bg-sky-900/25 dark:text-sky-300 dark:ring-sky-800/60",
  urgent: "bg-rose-600 text-white ring-rose-700 dark:bg-rose-500 dark:text-white dark:ring-rose-400",
};

export function Badge({ tone = "neutral", children, dot, className }: { tone?: Tone; children: ReactNode; dot?: boolean; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

const PRIORITY_TONE: Record<PriorityClass, Tone> = { urgent: "urgent", normal: "info", flexible: "neutral" };

export function PriorityBadge({ priority }: { priority: PriorityClass | null | undefined }) {
  if (!priority) return null;
  return <Badge tone={PRIORITY_TONE[priority]}>{priority}</Badge>;
}

/** Row/card accent for urgency highlighting in operator views. */
export const urgencyRing = (priority: PriorityClass | null | undefined) =>
  priority === "urgent"
    ? "border-l-4 border-l-rose-500 bg-rose-50/60 dark:bg-rose-950/20"
    : priority === "normal"
      ? "border-l-4 border-l-sky-400"
      : "border-l-4 border-l-transparent";
