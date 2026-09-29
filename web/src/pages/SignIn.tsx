import { Eye, EyeOff, LogIn } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { AuthLayout } from "./AuthLayout";

const DEMO = [
  { label: "Demo driver", email: "driver@gridpulse.local", password: "Driver123!" },
  { label: "Demo operator", email: "operator@gridpulse.local", password: "Operator123!" },
];

export default function SignIn() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoUsers, setDemoUsers] = useState(false);

  useEffect(() => {
    fetch("/health")
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => setDemoUsers(Boolean(h?.demo_users)))
      .catch(() => undefined);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await signIn(email, password);
      // only honour a return path that belongs to the signed-in role
      const target = from && from.startsWith(homeFor(user.role)) ? from : homeFor(user.role);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to find a charger or run your stations."
      footer={
        <>
          New to GridPulse?{" "}
          <Link to="/signup" className="font-semibold text-brand-700 hover:underline dark:text-brand-400">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
        />
        <div className="relative">
          <Field
            label="Password"
            type={show ? "text" : "password"}
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? "Hide password" : "Show password"}
            className="absolute right-3 top-[30px] text-slate-400 hover:text-slate-600"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        <Button type="submit" size="lg" block loading={busy} icon={<LogIn className="h-4 w-4" />} disabled={!email || !password}>
          Sign in
        </Button>
      </form>

      {demoUsers && (
        <div className="mt-6 rounded-xl border border-dashed border-slate-300 p-3 dark:border-ink-600">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Development demo accounts</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {DEMO.map((d) => (
              <Button
                key={d.email}
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  setEmail(d.email);
                  setPassword(d.password);
                }}
              >
                {d.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </AuthLayout>
  );
}
