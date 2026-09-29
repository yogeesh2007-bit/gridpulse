import { LogOut } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { cx } from "../../lib/format";
import { Badge } from "../ui/Badge";
import { ConnectionPill } from "./ConnectionPill";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";

export interface NavItem {
  key: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  badge?: number;
}

interface Props {
  basePath: string; // e.g. /app/driver
  items: NavItem[];
  title: string;
  subtitle?: string;
  children: ReactNode;
}

/** Read the active tab from `?tab=` (falls back to the first item). */
export function useTab(items: NavItem[]): [string, (key: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const active = items.some((i) => i.key === raw) ? (raw as string) : items[0].key;
  return [active, (key) => setParams({ tab: key }, { replace: false })];
}

/** Sidebar on desktop, bottom navigation on mobile, sticky header on both. */
export function AppShell({ basePath, items, title, subtitle, children }: Props) {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [active] = useTab(items);

  const leave = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  const linkTo = (key: string) => `${basePath}?tab=${key}`;

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[264px_minmax(0,1fr)]">
      {/* ---- sidebar (desktop) ---- */}
      <aside className="sticky top-0 hidden h-screen flex-col border-r border-slate-200 bg-white px-4 py-5 dark:border-ink-700 dark:bg-ink-900 lg:flex">
        <NavLink to="/" aria-label="GridPulse home" className="px-2">
          <Logo />
        </NavLink>
        <nav aria-label="Main" className="mt-8 flex flex-1 flex-col gap-1">
          {items.map((it) => {
            const on = it.key === active;
            return (
              <NavLink
                key={it.key}
                to={linkTo(it.key)}
                aria-current={on ? "page" : undefined}
                className={cx(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors",
                  on
                    ? "bg-brand-50 text-brand-800 dark:bg-brand-900/30 dark:text-brand-300"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-ink-800",
                )}
              >
                <it.icon className="h-5 w-5" />
                <span className="flex-1">{it.label}</span>
                {!!it.badge && <Badge tone="urgent">{it.badge}</Badge>}
              </NavLink>
            );
          })}
        </nav>
        <div className="rounded-2xl border border-slate-200 p-3 dark:border-ink-700">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-full bg-brand-100 text-sm font-bold text-brand-800 dark:bg-brand-900/40 dark:text-brand-300">
              {user?.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{user?.name}</p>
              <p className="truncate text-xs capitalize text-slate-500 dark:text-slate-400">{user?.role}</p>
            </div>
            <ThemeToggle />
          </div>
          <button
            type="button"
            onClick={leave}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-ink-800"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </aside>

      {/* ---- content ---- */}
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-slate-50/85 backdrop-blur dark:border-ink-700/80 dark:bg-ink-900/85">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <Logo compact className="lg:hidden" />
              <div className="min-w-0">
                <h1 className="truncate text-lg font-bold leading-tight tracking-tight text-slate-900 dark:text-white">{title}</h1>
                {subtitle && <p className="truncate text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <ConnectionPill />
              <div className="flex items-center lg:hidden">
                <ThemeToggle />
                <button
                  type="button"
                  onClick={leave}
                  aria-label="Sign out"
                  className="grid h-9 w-9 place-items-center rounded-xl text-slate-500 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-ink-800"
                >
                  <LogOut className="h-5 w-5" />
                </button>
              </div>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-28 pt-5 lg:px-8 lg:pb-12">{children}</main>
      </div>

      {/* ---- bottom navigation (mobile) ---- */}
      <nav
        aria-label="Main"
        className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 backdrop-blur dark:border-ink-700 dark:bg-ink-900/95 lg:hidden"
      >
        <ul className="mx-auto grid max-w-lg" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
          {items.map((it) => {
            const on = it.key === active;
            return (
              <li key={it.key}>
                <NavLink
                  to={linkTo(it.key)}
                  aria-current={on ? "page" : undefined}
                  className={cx(
                    "relative flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-semibold",
                    on ? "text-brand-700 dark:text-brand-400" : "text-slate-500 dark:text-slate-400",
                  )}
                >
                  <span className="relative">
                    <it.icon className="h-6 w-6" />
                    {!!it.badge && (
                      <span className="absolute -right-2 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
                        {it.badge}
                      </span>
                    )}
                  </span>
                  {it.label}
                  {on && <span className="absolute inset-x-6 top-0 h-0.5 rounded-full bg-brand-500" />}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
