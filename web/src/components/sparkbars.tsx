import { cn } from "@/lib/utils";

/**
 * Last four earnings reactions as signed bars around a zero axis.
 * Four numbers in a 56px cell would be unreadable; the shape is not.
 */
export function SparkBars({
  values,
  className,
}: {
  values: number[] | null | undefined;
  className?: string;
}) {
  if (!values || values.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  const max = Math.max(...values.map((v) => Math.abs(v)), 1);

  return (
    <span
      className={cn("inline-flex h-4 items-center gap-[3px]", className)}
      title={values.map((v) => `${v > 0 ? "+" : ""}${v}%`).join("  ")}
    >
      {values.map((v, i) => {
        const h = Math.max(2, (Math.abs(v) / max) * 7);
        return (
          <span
            key={i}
            className="relative flex h-4 w-[5px] flex-col justify-center"
            aria-hidden
          >
            <span
              className={cn(
                "absolute left-0 w-full rounded-[1px]",
                v >= 0 ? "bg-pos/75 bottom-1/2" : "bg-neg/75 top-1/2",
              )}
              style={{ height: `${h}px` }}
            />
          </span>
        );
      })}
    </span>
  );
}
