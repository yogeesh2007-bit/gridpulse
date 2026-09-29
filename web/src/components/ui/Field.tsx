import type { InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import { clamp, cx } from "../../lib/format";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
}

export function Field({ label, hint, error, className, id, ...rest }: FieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={className}>
      <label htmlFor={fid} className="label">
        {label}
      </label>
      <input
        id={fid}
        {...rest}
        aria-invalid={!!error}
        aria-describedby={error ? `${fid}-err` : hint ? `${fid}-hint` : undefined}
        className={cx("input", error && "border-red-400 focus:border-red-500 dark:border-red-500")}
      />
      {error ? (
        <p id={`${fid}-err`} className="mt-1 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${fid}-hint`} className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

/** A percentage input: slider + number box that stay in sync (mobile-friendly). */
export function PercentField({ label, value, onChange, min = 0, max = 100, error }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  error?: string | null;
}) {
  const id = useId();
  return (
    <div>
      <div className="flex items-end justify-between">
        <label htmlFor={id} className="label !mb-0">
          {label}
        </label>
        <div className="flex items-center gap-1">
          <input
            type="number"
            inputMode="numeric"
            min={min}
            max={max}
            value={Number.isFinite(value) ? value : ""}
            onChange={(e) => onChange(e.target.value === "" ? NaN : clamp(Number(e.target.value), min, max))}
            aria-label={`${label} (number)`}
            className="input tabular !w-16 !px-2 !py-1 text-center font-semibold"
          />
          <span className="text-sm text-slate-500">%</span>
        </div>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={Number.isFinite(value) ? value : min}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 h-2 w-full cursor-pointer"
      />
      {error && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
