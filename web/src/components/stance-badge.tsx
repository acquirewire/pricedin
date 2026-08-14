import { cn } from "@/lib/utils";
import type { Tone } from "@/lib/types";

/**
 * Deliberately quiet. The backtest found no directional edge, so a loud
 * green "BUY" pill would be making a claim the evidence does not support.
 * A dot plus text carries the reading without overstating it.
 */
const TONE: Record<Tone, { dot: string; text: string }> = {
  pos: { dot: "bg-pos", text: "text-pos" },
  "lean-pos": { dot: "bg-pos/55", text: "text-foreground" },
  neutral: { dot: "bg-muted-foreground/40", text: "text-muted-foreground" },
  "lean-neg": { dot: "bg-neg/55", text: "text-foreground" },
  neg: { dot: "bg-neg", text: "text-neg" },
};

export function StanceBadge({
  stance,
  tone,
  className,
}: {
  stance: string;
  tone: Tone;
  className?: string;
}) {
  const t = TONE[tone] ?? TONE.neutral;
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap", className)}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", t.dot)} aria-hidden />
      <span className={cn("text-[12.5px]", t.text)}>{stance}</span>
    </span>
  );
}
