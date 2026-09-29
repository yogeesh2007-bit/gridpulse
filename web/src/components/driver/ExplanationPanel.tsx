import { Bot, Lightbulb, Sparkles } from "lucide-react";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Section } from "../ui/Card";
import type { Explanation } from "../../lib/types";

interface Props {
  explanation: Explanation;
  aiAvailable: boolean;
  aiLoading: boolean;
  aiNote: string | null; // why the AI rewrite was not used, if it was not
  onRewrite: () => void;
}

/** Why this station was chosen. Deterministic text first; an optional AI rewrite of the same facts. */
export function ExplanationPanel({ explanation, aiAvailable, aiLoading, aiNote, onRewrite }: Props) {
  return (
    <Section
      title="Why this station?"
      icon={<Lightbulb className="h-5 w-5" />}
      action={
        explanation.source === "llm" ? (
          <Badge tone="info">
            <Bot className="h-3.5 w-3.5" /> AI-reworded
          </Badge>
        ) : (
          <Badge tone="neutral">Rule-based</Badge>
        )
      }
    >
      <p className="text-[15px] leading-relaxed text-slate-800 dark:text-slate-200" data-testid="explanation-text">
        {explanation.text}
      </p>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        {explanation.source === "llm"
          ? `Reworded by an AI model${explanation.model ? ` (${explanation.model})` : ""}. The ranking itself is computed by a deterministic formula; AI never decides.`
          : "Generated from the deterministic scoring formula. AI is optional and only rewords this text; it never decides."}
      </p>
      {aiNote && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{aiNote}</p>}
      {aiAvailable && explanation.source !== "llm" && (
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={onRewrite} loading={aiLoading} icon={<Sparkles className="h-4 w-4" />}>
            Reword with AI
          </Button>
        </div>
      )}
    </Section>
  );
}
