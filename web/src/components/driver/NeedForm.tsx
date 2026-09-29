import { BatteryCharging, ChevronDown, Search } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { cx } from "../../lib/format";
import { Button } from "../ui/Button";
import { Section } from "../ui/Card";
import { Field, PercentField } from "../ui/Field";

export interface NeedValues {
  soc: number;
  target: number;
  deadline: number; // minutes from now
  batteryKwh: number;
  maxKw: number;
}

export const DEFAULT_NEED: NeedValues = { soc: 20, target: 80, deadline: 120, batteryKwh: 40, maxKw: 50 };

const DEADLINE_PRESETS = [
  { label: "45 min", minutes: 45 },
  { label: "1 h", minutes: 60 },
  { label: "90 min", minutes: 90 },
  { label: "2 h", minutes: 120 },
  { label: "4 h", minutes: 240 },
];

interface Props {
  values: NeedValues;
  onChange: (v: NeedValues) => void;
  onSubmit: () => void;
  loading: boolean;
  hasPosition: boolean;
  submitLabel: string;
}

export function NeedForm({ values, onChange, onSubmit, loading, hasPosition, submitLabel }: Props) {
  const [touched, setTouched] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const set = (patch: Partial<NeedValues>) => onChange({ ...values, ...patch });

  const errors = useMemo(() => {
    const e: Partial<Record<keyof NeedValues, string>> = {};
    if (!Number.isFinite(values.soc)) e.soc = "Enter your current charge";
    if (!Number.isFinite(values.target) || values.target < 1) e.target = "Enter a target charge";
    else if (Number.isFinite(values.soc) && values.target <= values.soc) e.target = "Target must be higher than the current charge";
    if (!Number.isFinite(values.deadline) || values.deadline < 5) e.deadline = "Give a deadline of at least 5 minutes";
    else if (values.deadline > 1440) e.deadline = "Deadline must be within 24 hours";
    if (!Number.isFinite(values.batteryKwh) || values.batteryKwh < 10 || values.batteryKwh > 250) e.batteryKwh = "10 to 250 kWh";
    if (!Number.isFinite(values.maxKw) || values.maxKw < 3 || values.maxKw > 350) e.maxKw = "3 to 350 kW";
    return e;
  }, [values]);
  const valid = Object.keys(errors).length === 0;

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    setTouched(true);
    if (valid && hasPosition) onSubmit();
  };
  const err = (k: keyof NeedValues) => (touched ? (errors[k] ?? null) : null);

  return (
    <Section title="Charging need" icon={<BatteryCharging className="h-5 w-5" />} subtitle="What do you need, and by when?">
      <form onSubmit={submit} className="space-y-5" noValidate>
        <div className="grid gap-5 sm:grid-cols-2">
          <PercentField label="Current charge" value={values.soc} onChange={(v) => set({ soc: v })} error={err("soc")} min={0} max={99} />
          <PercentField label="Target charge" value={values.target} onChange={(v) => set({ target: v })} error={err("target")} min={1} max={100} />
        </div>

        <div>
          <Field
            label="Must be done within (minutes)"
            type="number"
            inputMode="numeric"
            min={5}
            max={1440}
            value={Number.isFinite(values.deadline) ? values.deadline : ""}
            onChange={(e) => set({ deadline: e.target.value === "" ? NaN : Number(e.target.value) })}
            error={err("deadline")}
          />
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Deadline presets">
            {DEADLINE_PRESETS.map((p) => (
              <button
                key={p.minutes}
                type="button"
                onClick={() => set({ deadline: p.minutes })}
                aria-pressed={values.deadline === p.minutes}
                className={cx(
                  "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                  values.deadline === p.minutes
                    ? "border-brand-500 bg-brand-50 text-brand-800 dark:bg-brand-900/30 dark:text-brand-300"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-ink-600 dark:text-slate-300 dark:hover:bg-ink-800",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <button
            type="button"
            onClick={() => setAdvanced((a) => !a)}
            aria-expanded={advanced}
            className="flex items-center gap-1 text-sm font-semibold text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
          >
            <ChevronDown className={cx("h-4 w-4 transition-transform", advanced && "rotate-180")} /> Vehicle details
          </button>
          {advanced && (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Field label="Battery (kWh)" type="number" inputMode="decimal" value={Number.isFinite(values.batteryKwh) ? values.batteryKwh : ""} onChange={(e) => set({ batteryKwh: e.target.value === "" ? NaN : Number(e.target.value) })} error={err("batteryKwh")} />
              <Field label="Max charge rate (kW)" type="number" inputMode="decimal" value={Number.isFinite(values.maxKw) ? values.maxKw : ""} onChange={(e) => set({ maxKw: e.target.value === "" ? NaN : Number(e.target.value) })} error={err("maxKw")} />
            </div>
          )}
        </div>

        {!hasPosition && touched && <p className="text-sm text-amber-700 dark:text-amber-300">Share or enter your location first (see above).</p>}
        <Button type="submit" size="lg" block loading={loading} icon={<Search className="h-5 w-5" />}>
          {submitLabel}
        </Button>
      </form>
    </Section>
  );
}
