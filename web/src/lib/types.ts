export type Tone = "pos" | "lean-pos" | "neutral" | "lean-neg" | "neg";

export interface Verdict {
  stance: string;
  tone: Tone;
  score: number;
  supports: string[];
  against: string[];
  neutral: string[];
  caveat: string | null;
}

export interface TradePlan {
  symbol: string;
  style: "through_print" | "post_print_drift" | "premium_sell";
  direction: string;
  tradeable: boolean;
  predicted_move_pct: number | null;
  implied_move_pct: number | null;
  entry_rule: string;
  entry_ref: number | null;
  tp_price: number | null;
  sl_price: number | null;
  tp_pct: number | null;
  sl_pct: number | null;
  hold_days: number | null;
  size_pct: number | null;
  ev_bps: number | null;
  p_win: number | null;
  risk_note: string;
  reasons: string[];
}

export interface EarningsEvent {
  symbol: string;
  name: string | null;
  report_date: string;
  session: string | null;
  days_to_report: number;
  market_cap: number | null;
  price: number | null;
  eps_forecast: number | null;
  n_estimates: number | null;
  n_analysts: number | null;
  p_beat: number | null;
  p_beat_n: number | null;
  beat_rate_8: number | null;
  surp_mean_4: number | null;
  rev_chg_7d: number | null;
  rev_chg_30d: number | null;
  rev_chg_90d: number | null;
  up_30d: number | null;
  down_30d: number | null;
  n_observed: number | null;
  snap_span_days: number | null;
  implied_move_pct: number | null;
  implied_expiry: string | null;
  realised_move_med_8: number | null;
  realised_move_max_8: number | null;
  implied_vs_realised: number | null;
  runup_10d: number | null;
  runup_60d: number | null;
  vol_20d: number | null;
  reac_mean_8: number | null;
  reac_median_8: number | null;
  reaction_slope: number | null;
  beat_and_fell_rate: number | null;
  last_reactions: number[] | null;
  n_quarters: number | null;
  size_pct: number | null;
  size_basis: string | null;
  size_risk_pct: number | null;
  verdict?: Verdict;
  plans?: TradePlan[];
}

export interface Book {
  book: string;
  description: string;
  role: "strategy" | "control" | "benchmark";
  trades: number;
  hit_rate: number | null;
  avg_ret_pct: number | null;
  net_pnl: number | null;
  costs_paid: number | null;
  equity: number | null;
  return_pct: number | null;
  sharpe: number | null;
  max_dd_pct: number | null;
}

export interface CurvePoint {
  date: string;
  equity: number;
}

export interface Trade {
  book: string;
  symbol: string;
  side: string;
  entry_date: string;
  entry_price: number;
  exit_price: number;
  exit_date: string;
  exit_reason: string;
  pnl: number;
  ret_pct: number;
}

export interface OpenPosition {
  book: string;
  symbol: string;
  side: string;
  entry_date: string;
  entry_price: number;
  qty: number;
}

export interface Portfolio {
  books: Book[];
  curves: Record<string, CurvePoint[]>;
  blotter: Trade[];
  open: OpenPosition[];
  period: { start?: string; end?: string };
  settings: {
    starting_cash: number;
    max_concurrent: number;
    cost_bps: number;
    slippage_bps: number;
  };
}

export interface StrategyResult {
  name: string;
  period: string;
  n: number;
  mean_bps: number | null;
  net_mean_bps: number | null;
  hit_rate: number | null;
  t_stat: number | null;
  control_mean_bps: number | null;
  excess_bps: number | null;
  t_vs_control: number | null;
  note?: string;
}

export interface MagnitudeResult {
  name: string;
  period: string;
  n: number;
  mean_bps: number | null;
  control_mean_bps: number | null;
  ratio: number | null;
  note?: string;
}

export interface Survivor {
  name: string;
  survived: boolean;
  beats_zero: boolean;
  beats_control: boolean;
  n_train: number;
  n_validate: number;
  net_bps_train: number;
  net_bps_validate: number;
  excess_train: number;
  excess_validate: number;
  t_ctrl_train: number;
  t_ctrl_validate: number;
}

export interface Backtest {
  strategies: StrategyResult[];
  magnitude: MagnitudeResult[];
  survivors: Survivor[];
  move_model?: {
    corr_train: number;
    corr_validate: number;
    n_train: number;
    calibration: number;
  };
  splits: { train_end: string; validate_end: string };
}

export interface Meta {
  generated: string;
  universe: number;
  snapshot_rows: number;
  snapshot_observed: number;
  snapshot_span: { start?: string; end?: string };
  historical_prints: number;
}
