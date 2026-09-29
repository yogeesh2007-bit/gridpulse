import { UserPlus } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { homeFor, useAuth } from "../auth/AuthContext";
import { Alert } from "../components/ui/Alert";
import { Button } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { Segmented } from "../components/ui/Segmented";
import type { Role } from "../lib/types";
import { AuthLayout } from "./AuthLayout";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function SignUp() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [role, setRole] = useState<Role>("driver");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const problems = useMemo(() => {
    const p: Partial<Record<"name" | "email" | "password" | "code", string>> = {};
    if (!name.trim()) p.name = "Enter your name";
    if (!EMAIL_RE.test(email.trim())) p.email = "Enter a valid email address";
    if (password.length < 8) p.password = "Use at least 8 characters";
    else if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) p.password = "Include at least one letter and one number";
    if (role === "operator" && !code.trim()) p.code = "Operator sign-up needs an invite code";
    return p;
  }, [name, email, password, code, role]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(problems).length) return;
    setError(null);
    setBusy(true);
    try {
      const user = await signUp({ name: name.trim(), email: email.trim(), password, role, operator_code: role === "operator" ? code.trim() : undefined });
      navigate(homeFor(user.role), { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account");
      setBusy(false);
    }
  };

  const show = (k: keyof typeof problems) => (touched ? (problems[k] ?? null) : null);

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Drivers get smart charger recommendations. Operators manage stations."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/signin" className="font-semibold text-brand-700 hover:underline dark:text-brand-400">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <div>
          <span className="label">I am a</span>
          <Segmented
            label="Account type"
            value={role}
            onChange={setRole}
            options={[
              { value: "driver", label: "Driver" },
              { value: "operator", label: "Operator" },
            ]}
          />
        </div>
        <Field label="Name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} error={show("name")} />
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={show("email")}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={show("password")}
          hint="At least 8 characters with a letter and a number."
        />
        {role === "operator" && (
          <Field
            label="Operator invite code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            error={show("code")}
            hint="Ask your administrator. Operator accounts can control stations."
            autoComplete="off"
          />
        )}
        <Button type="submit" size="lg" block loading={busy} icon={<UserPlus className="h-4 w-4" />}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
