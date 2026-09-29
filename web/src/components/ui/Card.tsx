import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "../../lib/format";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx("card", className)} />;
}

interface SectionProps {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
  pad?: boolean;
}

/** A titled card: icon + title + optional subtitle and right-aligned action. */
export function Section({ title, subtitle, action, icon, children, className, pad = true }: SectionProps) {
  return (
    <section className={cx("card", className)}>
      <header className="flex items-start justify-between gap-3 px-4 pt-4 sm:px-5 sm:pt-5">
        <div className="flex min-w-0 items-start gap-2.5">
          {icon && <span className="mt-0.5 text-brand-600 dark:text-brand-400">{icon}</span>}
          <div className="min-w-0">
            <h2 className="text-base font-semibold leading-6 text-slate-900 dark:text-white">{title}</h2>
            {subtitle && <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      <div className={cx(pad && "p-4 sm:p-5", !pad && "pt-3")}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const tones = {
    default: "text-slate-900 dark:text-white",
    good: "text-brand-700 dark:text-brand-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-red-600 dark:text-red-400",
  };
  return (
    <div className="card card-pad">
      <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
        {icon}
      </div>
      <div className={cx("tabular mt-1 text-2xl font-bold tracking-tight sm:text-3xl", tones[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{hint}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-slate-300 px-6 py-10 text-center dark:border-ink-600">
      {icon && <div className="text-slate-400">{icon}</div>}
      <p className="font-semibold text-slate-700 dark:text-slate-200">{title}</p>
      {children && <p className="max-w-sm text-sm text-slate-500 dark:text-slate-400">{children}</p>}
    </div>
  );
}
