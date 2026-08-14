"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Search } from "lucide-react";

import { StanceBadge } from "@/components/stance-badge";
import { SparkBars } from "@/components/sparkbars";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { EarningsEvent } from "@/lib/types";
import {
  DASH,
  countdown,
  marketCap,
  num,
  pct,
  ratio,
  sessionLabel,
  shortDate,
  share,
  signed,
  toneOf,
} from "@/lib/format";

// Base UI's Select.Value renders the raw value unless given a render function,
// so the trigger needs an explicit value -> label map.
const WINDOW_LABELS: Record<string, string> = {
  all: "Next 21 days",
  "7": "Next 7 days",
  "3": "Next 3 days",
  "0": "Reporting today",
};

const STANCE_LABELS: Record<string, string> = {
  all: "All readings",
  pos: "Favourable",
  "lean-pos": "Leaning favourable",
  neutral: "Neutral",
  "lean-neg": "Leaning unfavourable",
  neg: "Unfavourable",
};

type SortKey =
  | "days_to_report"
  | "symbol"
  | "market_cap"
  | "stance"
  | "p_beat"
  | "implied_move_pct"
  | "realised_move_med_8"
  | "implied_vs_realised"
  | "runup_10d"
  | "rev_chg_30d";

const COLUMNS: {
  key: SortKey;
  label: string;
  align?: "right";
  hint?: string;
  hideBelow?: string;
}[] = [
  { key: "symbol", label: "Company" },
  { key: "days_to_report", label: "Reports", align: "right" },
  { key: "market_cap", label: "Cap", align: "right", hideBelow: "md" },
  { key: "stance", label: "Reading" },
  {
    key: "p_beat",
    label: "Beat freq",
    align: "right",
    hint: "Historical frequency with which names with this record beat consensus",
  },
  {
    key: "rev_chg_30d",
    label: "Rev 30d",
    align: "right",
    hint: "Change in consensus EPS over 30 days",
    hideBelow: "lg",
  },
  {
    key: "implied_move_pct",
    label: "Implied",
    align: "right",
    hint: "ATM straddle on the first expiry after the print, as % of spot",
  },
  {
    key: "realised_move_med_8",
    label: "Realised",
    align: "right",
    hint: "Median absolute one-day move over the last eight prints",
  },
  {
    key: "implied_vs_realised",
    label: "Imp ÷ Real",
    align: "right",
    hint: "Above 1 means options are charging more than this stock usually moves",
  },
  { key: "runup_10d", label: "Run-up 10d", align: "right", hideBelow: "sm" },
  { key: "last_reactions" as SortKey, label: "Last 4", hideBelow: "xl" },
];

function sortValue(e: EarningsEvent, key: SortKey): number | string | null {
  if (key === "stance") return e.verdict?.score ?? 0;
  if (key === "symbol") return e.symbol;
  return (e[key as keyof EarningsEvent] as number) ?? null;
}

export function EarningsTable({ events }: { events: EarningsEvent[] }) {
  const [query, setQuery] = useState("");
  const [stance, setStance] = useState("all");
  const [window, setWindow] = useState("all");
  const [sort, setSort] = useState<SortKey>("days_to_report");
  const [dir, setDir] = useState<1 | -1>(1);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = events.filter((e) => {
      if (
        q &&
        !e.symbol.toLowerCase().includes(q) &&
        !(e.name ?? "").toLowerCase().includes(q)
      )
        return false;
      if (stance !== "all" && e.verdict?.tone !== stance) return false;
      if (window !== "all" && e.days_to_report > Number(window)) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      const x = sortValue(a, sort);
      const y = sortValue(b, sort);
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === "string" || typeof y === "string")
        return dir * String(x).localeCompare(String(y));
      return dir * (x - y);
    });
  }, [events, query, stance, window, sort, dir]);

  function toggle(key: SortKey) {
    if (key === sort) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSort(key);
      // Text sorts ascending, figures descending — what you almost always want.
      setDir(key === "symbol" ? 1 : -1);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2.5 pb-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ticker or company"
            className="h-8 w-56 pl-8 text-[13px]"
            aria-label="Filter by ticker or company"
          />
        </div>

        <Select value={window} onValueChange={(v) => setWindow(String(v))}>
          <SelectTrigger className="h-8 w-[148px] text-[13px]" size="sm">
            <SelectValue>
              {(v) => WINDOW_LABELS[String(v)] ?? WINDOW_LABELS.all}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {Object.entries(WINDOW_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={stance} onValueChange={(v) => setStance(String(v))}>
          <SelectTrigger className="h-8 w-[178px] text-[13px]" size="sm">
            <SelectValue>
              {(v) => STANCE_LABELS[String(v)] ?? STANCE_LABELS.all}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {Object.entries(STANCE_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <span className="ml-auto font-mono text-[11.5px] text-muted-foreground">
          {rows.length} of {events.length}
        </span>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[900px] border-collapse">
          <thead>
            <tr className="border-b bg-card">
              {COLUMNS.map((c) => {
                const active = sort === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    title={c.hint}
                    className={cn(
                      "label sticky top-13 z-10 bg-card px-3 py-2.5 font-medium select-none",
                      c.align === "right" ? "text-right" : "text-left",
                      c.hideBelow === "sm" && "hidden sm:table-cell",
                      c.hideBelow === "md" && "hidden md:table-cell",
                      c.hideBelow === "lg" && "hidden lg:table-cell",
                      c.hideBelow === "xl" && "hidden xl:table-cell",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className={cn(
                        "inline-flex items-center gap-1 transition-colors hover:text-foreground",
                        active && "text-foreground",
                        c.align === "right" && "flex-row-reverse",
                      )}
                    >
                      {c.label}
                      {active &&
                        (dir === 1 ? (
                          <ArrowUp className="size-3" />
                        ) : (
                          <ArrowDown className="size-3" />
                        ))}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr
                key={e.symbol}
                className="border-b border-border/60 transition-colors last:border-0 hover:bg-accent/45"
              >
                <td className="px-3 py-2">
                  <Link
                    href={`/s/${e.symbol}`}
                    className="block outline-none focus-visible:underline"
                  >
                    <span className="text-[13px] font-semibold">{e.symbol}</span>
                    <span className="mt-0.5 block max-w-[210px] truncate text-[11.5px] text-muted-foreground">
                      {e.name}
                    </span>
                  </Link>
                </td>

                <td className="px-3 py-2 text-right">
                  <span className="num block">{countdown(e.days_to_report)}</span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {shortDate(e.report_date)} · {sessionLabel(e.session)}
                  </span>
                </td>

                <td className="hidden px-3 py-2 text-right md:table-cell">
                  <span className="num">{marketCap(e.market_cap)}</span>
                </td>

                <td className="px-3 py-2">
                  {e.verdict ? (
                    <StanceBadge
                      stance={e.verdict.stance}
                      tone={e.verdict.tone}
                    />
                  ) : (
                    DASH
                  )}
                </td>

                <td className="px-3 py-2 text-right">
                  <span className="num">{share(e.p_beat)}</span>
                </td>

                <td className="hidden px-3 py-2 text-right lg:table-cell">
                  <span className={cn("num", toneOf(e.rev_chg_30d))}>
                    {signed(e.rev_chg_30d)}
                  </span>
                </td>

                <td className="px-3 py-2 text-right">
                  <span className="num">{pct(e.implied_move_pct)}</span>
                </td>

                <td className="px-3 py-2 text-right">
                  <span className="num text-muted-foreground">
                    {pct(e.realised_move_med_8)}
                  </span>
                </td>

                <td className="px-3 py-2 text-right">
                  <span
                    className={cn(
                      "num",
                      e.implied_vs_realised == null
                        ? "text-muted-foreground"
                        : e.implied_vs_realised >= 1.3
                          ? "text-neg"
                          : e.implied_vs_realised <= 0.85
                            ? "text-pos"
                            : "",
                    )}
                  >
                    {ratio(e.implied_vs_realised)}
                  </span>
                </td>

                <td className="hidden px-3 py-2 text-right sm:table-cell">
                  <span className={cn("num", toneOf(e.runup_10d))}>
                    {signed(e.runup_10d)}
                  </span>
                </td>

                <td className="hidden px-3 py-2 xl:table-cell">
                  <SparkBars values={e.last_reactions} />
                </td>
              </tr>
            ))}

            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-16 text-center text-[13px] text-muted-foreground"
                >
                  No companies match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {num(events.filter((e) => e.implied_move_pct != null).length, 0)} of{" "}
        {events.length} have a listed option chain covering the print; the rest
        show {DASH} rather than a guess. Sorted by{" "}
        <span className="font-mono">{sort.replace(/_/g, " ")}</span>.
      </p>
    </div>
  );
}
