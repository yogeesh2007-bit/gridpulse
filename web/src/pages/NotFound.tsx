import { Link } from "react-router-dom";
import { Logo } from "../components/layout/Logo";
import { Button } from "../components/ui/Button";

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center px-5 text-center">
      <div>
        <Logo className="mb-6" />
        <p className="text-6xl font-extrabold text-brand-600 dark:text-brand-400">404</p>
        <h1 className="mt-2 text-xl font-bold text-slate-900 dark:text-white">This page does not exist</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">The link may be old or mistyped.</p>
        <Link to="/" className="mt-6 inline-block">
          <Button>Back to home</Button>
        </Link>
      </div>
    </div>
  );
}
