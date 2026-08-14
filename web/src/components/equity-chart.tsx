"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { CurvePoint } from "@/lib/types";

/**
 * The control and the benchmark are drawn dashed and in grey. They are not
 * competing strategies — they are the yardsticks the strategies have to clear,
 * and the styling should say so before the legend does.
 */
const DASHED = new Set(["random", "spy_hold"]);

export function EquityChart({
  curves,
  startingCash,
}: {
  curves: Record<string, CurvePoint[]>;
  startingCash: number;
}) {
  const books = Object.keys(curves);
  if (books.length === 0) return null;

  const dates = Array.from(
    new Set(books.flatMap((b) => curves[b].map((p) => p.date))),
  ).sort();

  const data = dates.map((date) => {
    const row: Record<string, string | number> = { date };
    for (const b of books) {
      const hit = curves[b].find((p) => p.date === date);
      if (hit) row[b] = hit.equity;
    }
    return row;
  });

  const config: ChartConfig = Object.fromEntries(
    books.map((b, i) => [
      b,
      {
        label: b.replace(/_/g, " "),
        color: DASHED.has(b)
          ? "var(--muted-foreground)"
          : `var(--chart-${(i % 5) + 1})`,
      },
    ]),
  );

  return (
    <ChartContainer config={config} className="h-[330px] w-full">
      <LineChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
        <CartesianGrid vertical={false} strokeOpacity={0.5} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          minTickGap={64}
          tickMargin={10}
          tickFormatter={(v: string) =>
            new Date(v).toLocaleDateString("en-GB", {
              month: "short",
              year: "2-digit",
            })
          }
          className="text-[11px]"
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={46}
          tickMargin={6}
          tickFormatter={(v: number) => `${Math.round(v / 1000)}k`}
          className="text-[11px]"
        />
        <ReferenceLine
          y={startingCash}
          stroke="var(--muted-foreground)"
          strokeDasharray="3 3"
          strokeOpacity={0.6}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(v) =>
                new Date(String(v)).toLocaleDateString("en-GB", {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })
              }
              formatter={(value, name) => (
                <div className="flex w-full items-center justify-between gap-4">
                  <span className="text-muted-foreground">
                    {String(name).replace(/_/g, " ")}
                  </span>
                  <span className="font-mono tabular-nums">
                    ${Number(value).toLocaleString("en-GB", {
                      maximumFractionDigits: 0,
                    })}
                  </span>
                </div>
              )}
            />
          }
        />
        {books.map((b, i) => (
          <Line
            key={b}
            dataKey={b}
            type="monotone"
            stroke={
              DASHED.has(b)
                ? "var(--muted-foreground)"
                : `var(--chart-${(i % 5) + 1})`
            }
            strokeWidth={DASHED.has(b) ? 1.5 : 1.75}
            strokeDasharray={DASHED.has(b) ? "4 3" : undefined}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ChartContainer>
  );
}
