import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "../../lib/format";

type Kind = "error" | "warning" | "success" | "info";

const STYLE: Record<Kind, { box: string; icon: ReactNode }> = {
  error: {
    box: "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200",
    icon: <AlertCircle className="h-5 w-5 shrink-0" />,
  },
  warning: {
    box: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200",
    icon: <AlertTriangle className="h-5 w-5 shrink-0" />,
  },
  success: {
    box: "border-brand-200 bg-brand-50 text-brand-900 dark:border-brand-800/60 dark:bg-brand-900/25 dark:text-brand-200",
    icon: <CheckCircle2 className="h-5 w-5 shrink-0" />,
  },
  info: {
    box: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200",
    icon: <Info className="h-5 w-5 shrink-0" />,
  },
};

export function Alert({ kind = "info", title, children, className, action }: {
  kind?: Kind;
  title?: string;
  children?: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  const s = STYLE[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={cx("flex gap-3 rounded-xl border p-3 text-sm", s.box, className)}>
      {s.icon}
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title && "mt-0.5", "break-words")}>{children}</div>}
      </div>
      {action}
    </div>
  );
}
