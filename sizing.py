"""Position sizing.

Deliberately kept separate from the signal layer, and deliberately dumb.

`vol_target_size` embeds no view at all: it answers "how large can this be so
that a move of the size the market is pricing costs me no more than my risk
budget". That is arithmetic, not a recommendation.

`kelly_size` does embed a view, so it is only ever applied on top of an edge
that cleared the backtest gate, and always fractionally.
"""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class SizeResult:
    position_pct: float          # % of portfolio
    risk_pct: float              # % of portfolio at risk if expected move hits
    basis: str
    capped_by: str | None = None
    notes: str = ""


def vol_target_size(expected_move_pct: float,
                    risk_budget_pct: float = config.DEFAULT_RISK_BUDGET_PCT,
                    max_position_pct: float = config.MAX_POSITION_PCT,
                    stress_multiple: float = 1.5) -> SizeResult:
    """Size so a stress-case adverse move costs at most the risk budget.

    expected_move_pct : the one-sigma move, e.g. the implied move from the
                        straddle. stress_multiple scales it to something closer
                        to a bad day, because earnings moves have fat tails and
                        sizing off the median is how people get hurt.
    """
    if not expected_move_pct or expected_move_pct <= 0:
        return SizeResult(0.0, 0.0, "no expected move available",
                          notes="Cannot size without an implied or realised move.")

    adverse = expected_move_pct * stress_multiple
    raw = 100.0 * risk_budget_pct / adverse

    capped_by = None
    pos = raw
    if pos > max_position_pct:
        pos, capped_by = max_position_pct, "max position limit"

    return SizeResult(
        position_pct=round(pos, 2),
        risk_pct=round(pos * adverse / 100.0, 2),
        basis=f"{risk_budget_pct:.2f}% budget / ({expected_move_pct:.1f}% "
              f"expected move x {stress_multiple:g} stress)",
        capped_by=capped_by,
        notes="Vol targeting only. No directional view is embedded in this number.",
    )


def kelly_size(win_prob: float, win_pct: float, loss_pct: float,
               fraction: float = config.KELLY_FRACTION,
               max_position_pct: float = config.MAX_POSITION_PCT) -> SizeResult:
    """Fractional Kelly. Only valid on a backtest-validated edge."""
    if not (0 < win_prob < 1) or win_pct <= 0 or loss_pct <= 0:
        return SizeResult(0.0, 0.0, "invalid inputs")

    b = win_pct / loss_pct
    edge = win_prob - (1 - win_prob) / b
    if edge <= 0:
        return SizeResult(0.0, 0.0, "no positive Kelly edge",
                          notes="Expectancy is negative or zero at these odds.")

    full = edge / 1.0
    pos = 100.0 * full * fraction
    capped_by = None
    if pos > max_position_pct:
        pos, capped_by = max_position_pct, "max position limit"

    return SizeResult(
        position_pct=round(pos, 2),
        risk_pct=round(pos * loss_pct / 100.0, 2),
        basis=f"{fraction:g}x Kelly at p={win_prob:.0%}, "
              f"win {win_pct:.1f}% / loss {loss_pct:.1f}%",
        capped_by=capped_by,
        notes="Requires a validated edge. Kelly on an unvalidated signal "
              "sizes confidence, not edge.",
    )
