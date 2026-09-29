import { ArrowRight, BatteryCharging, Cpu, Gauge, MapPinned, Route, ShieldCheck, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Logo } from "../components/layout/Logo";
import { ThemeToggle } from "../components/layout/ThemeToggle";
import { Button } from "../components/ui/Button";

const FEATURES = [
  { icon: Route, title: "Route-aware ranking", body: "Real road ETAs from OSRM with an honest haversine fallback, not just straight-line distance." },
  { icon: Timer, title: "Queue & wait prediction", body: "Priority-aware queue simulation predicts when a port will actually be yours." },
  { icon: Gauge, title: "Power-aware", body: "Site load vs limit is part of every score, so stations at their limit are avoided." },
  { icon: ShieldCheck, title: "Deterministic decisions", body: "A transparent formula decides. AI only rewrites the explanation and never controls anything." },
  { icon: Cpu, title: "Hardware-ready", body: "Simulated device today, ESP32 + INA219 + MOSFET tomorrow. Same protocol, clearly labelled." },
  { icon: MapPinned, title: "Live everywhere", body: "Your position and the station state stream over WebSockets to the operator dashboard." },
];

const STEPS = [
  ["Share your position", "Live location, or type one in."],
  ["Tell us your need", "Current and target charge, plus your deadline."],
  ["Get the best charger", "Ranked by earliest safe completion, with the reason why."],
];

export default function Landing() {
  const { status, user } = useAuth();
  const authed = status === "authed" && user;

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <Logo />
        <nav className="flex items-center gap-2" aria-label="Site">
          <ThemeToggle />
          {authed ? (
            <Link to={homeFor(user.role)}>
              <Button size="sm" icon={<ArrowRight className="h-4 w-4" />}>
                Open app
              </Button>
            </Link>
          ) : (
            <>
              <Link to="/signin" className="hidden sm:block">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link to="/signup">
                <Button size="sm">Get started</Button>
              </Link>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[420px] max-w-3xl rounded-full bg-brand-400/20 blur-3xl dark:bg-brand-500/10" />
          <div className="relative mx-auto max-w-4xl px-5 pb-16 pt-12 text-center sm:pt-20">
            <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 dark:border-brand-800/60 dark:bg-brand-900/30 dark:text-brand-300">
              <BatteryCharging className="h-3.5 w-3.5" /> Smart EV charging, engineered
            </span>
            <h1 className="mt-5 text-4xl font-extrabold leading-[1.1] tracking-tight text-slate-900 dark:text-white sm:text-6xl">
              Charge <span className="text-brand-600 dark:text-brand-400">smarter</span>, not just nearer.
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-base text-slate-600 dark:text-slate-300 sm:text-lg">
              GridPulse recommends the station that gets you charged earliest and safest, weighing travel time, queue, charging speed, site
              power and how urgent your trip is. Operators watch and steer it live.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link to={authed ? homeFor(user.role) : "/signup"}>
                <Button size="lg" icon={<ArrowRight className="h-5 w-5" />}>
                  {authed ? "Open the app" : "Find my charger"}
                </Button>
              </Link>
              {!authed && (
                <Link to="/signin">
                  <Button size="lg" variant="secondary">
                    Sign in
                  </Button>
                </Link>
              )}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-10" aria-labelledby="how">
          <h2 id="how" className="text-center text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
            How it works
          </h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-3">
            {STEPS.map(([title, body], i) => (
              <li key={title} className="card card-pad">
                <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-600 text-sm font-bold text-white dark:bg-brand-500 dark:text-ink-950">
                  {i + 1}
                </span>
                <h3 className="mt-3 font-semibold text-slate-900 dark:text-white">{title}</h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-10" aria-labelledby="features">
          <h2 id="features" className="text-center text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
            Built like a real system
          </h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="card card-pad">
                <Icon className="h-6 w-6 text-brand-600 dark:text-brand-400" />
                <h3 className="mt-3 font-semibold text-slate-900 dark:text-white">{title}</h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="mx-auto max-w-6xl px-5 py-10 text-center text-xs text-slate-500 dark:text-slate-400">
        GridPulse is a low-voltage smart-charging prototype. It is not a production EV charger and must never switch mains power.
      </footer>
    </div>
  );
}
