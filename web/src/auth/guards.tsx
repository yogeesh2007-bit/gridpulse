import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { FullPageSpinner } from "../components/ui/Spinner";
import type { Role } from "../lib/types";
import { homeFor, useAuth } from "./AuthContext";

/** Only signed-in users pass; optionally only a specific role (others are sent to their own area). */
export function RequireAuth({ role, children }: { role?: Role; children: ReactNode }) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") return <FullPageSpinner label="Restoring your session…" />;
  if (status === "anon" || !user) {
    return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />;
  }
  if (role && user.role !== role) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}

/** Sign-in / sign-up pages: signed-in users skip straight to their area. */
export function RedirectIfAuthed({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  if (status === "loading") return <FullPageSpinner label="Loading…" />;
  if (status === "authed" && user) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}
