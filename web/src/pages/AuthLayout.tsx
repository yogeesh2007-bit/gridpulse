import { BatteryCharging, Gauge, MapPinned } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/layout/Logo";
import { ThemeToggle } from "../components/layout/ThemeToggle";

/** Split layout for sign-in / sign-up: brand panel on desktop, compact header on mobile. */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-ink-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-sky-500/10 blur-3xl" />
        <Link to="/" aria-label="GridPulse home" className="relative">
          <Logo />
        </Link>
        <div className="relative max-w-md">
          <h2 className="text-4xl font-bold leading-tight tracking-tight">The charger that finishes you first isn&apos;t always the nearest.</h2>
          <ul className="mt-8 space-y-5 text-slate-300">
            {[
              [MapPinned, "Route-aware", "Real road ETAs, with an automatic fallback when routing is unavailable."],
              [BatteryCharging, "Queue & power aware", "Wait time, site load and urgency decide, never just distance."],
              [Gauge, "Deterministic", "Every score is explained. AI only rewords it, and it never decides."],
            ].map(([Icon, head, body]) => {
              const I = Icon as typeof MapPinned;
              return (
                <li key={head as string} className="flex gap-3">
                  <I className="mt-0.5 h-5 w-5 shrink-0 text-brand-400" />
                  <p>
                    <span className="font-semibold text-white">{head as string}.</span> {body as string}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">Low-voltage prototype for smart-charging research. Not a production charger.</p>
      </div>

      <div className="flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 lg:justify-end">
          <Link to="/" className="lg:hidden" aria-label="GridPulse home">
            <Logo />
          </Link>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-5 pb-12">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white sm:text-3xl">{title}</h1>
          <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
          <div className="mt-7">{children}</div>
          <div className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">{footer}</div>
        </div>
      </div>
    </div>
  );
}
