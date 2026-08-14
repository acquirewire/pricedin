import eventsJson from "@/data/events.json";
import portfolioJson from "@/data/portfolio.json";
import backtestJson from "@/data/backtest.json";
import metaJson from "@/data/meta.json";

import type {
  Backtest,
  EarningsEvent,
  Meta,
  Portfolio,
} from "./types";

/**
 * The Python pipeline is the source of truth; these JSON files are a static
 * snapshot of its output, written by `python export_web.py`. Reading them at
 * build time means the site deploys as static files with no database and no
 * API to keep alive.
 */
export const events = eventsJson as unknown as EarningsEvent[];
export const portfolio = portfolioJson as unknown as Portfolio;
export const backtest = backtestJson as unknown as Backtest;
export const meta = metaJson as unknown as Meta;

export function getEvent(symbol: string): EarningsEvent | undefined {
  const s = symbol.toUpperCase();
  return events.find((e) => e.symbol.toUpperCase() === s);
}

export function allSymbols(): string[] {
  return events.map((e) => e.symbol);
}

/** Books minus the two yardsticks, which are presented separately. */
export function strategyBooks() {
  return portfolio.books.filter((b) => b.role === "strategy");
}

export function controlBook() {
  return portfolio.books.find((b) => b.role === "control");
}

export function benchmarkBook() {
  return portfolio.books.find((b) => b.role === "benchmark");
}

export const BOOK_COLOURS: Record<string, string> = {
  stance_long: "var(--chart-1)",
  stance_short: "var(--chart-2)",
  drift_long: "var(--chart-3)",
  cheap_vol: "var(--chart-4)",
  random: "var(--chart-5)",
  spy_hold: "var(--muted-foreground)",
};
