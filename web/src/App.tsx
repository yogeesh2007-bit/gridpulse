import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { homeFor, useAuth } from "./auth/AuthContext";
import { RedirectIfAuthed, RequireAuth } from "./auth/guards";
import { FullPageSpinner } from "./components/ui/Spinner";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";
import SignIn from "./pages/SignIn";
import SignUp from "./pages/SignUp";
import { LiveProvider } from "./realtime/LiveContext";

// the two work areas are code-split so the landing/sign-in pages stay light
const DriverPage = lazy(() => import("./pages/DriverPage"));
const OperatorPage = lazy(() => import("./pages/OperatorPage"));

/** /app -> the signed-in user's own area. */
function AppIndex() {
  const { status, user } = useAuth();
  if (status === "loading") return <FullPageSpinner label="Loading…" />;
  return <Navigate to={user ? homeFor(user.role) : "/signin"} replace />;
}

/** Everything under /app needs a session and shares one live WebSocket. */
function AppArea() {
  return (
    <RequireAuth>
      <LiveProvider>
        <Suspense fallback={<FullPageSpinner label="Loading…" />}>
          <Outlet />
        </Suspense>
      </LiveProvider>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/signin" element={<RedirectIfAuthed><SignIn /></RedirectIfAuthed>} />
      <Route path="/signup" element={<RedirectIfAuthed><SignUp /></RedirectIfAuthed>} />
      <Route path="/app" element={<AppArea />}>
        <Route index element={<AppIndex />} />
        <Route path="driver" element={<RequireAuth role="driver"><DriverPage /></RequireAuth>} />
        <Route path="operator" element={<RequireAuth role="operator"><OperatorPage /></RequireAuth>} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
