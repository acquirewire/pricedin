"""Data provider abstraction.

Everything the rest of the codebase needs from the outside world goes through
these functions. Today they are backed by Yahoo and Nasdaq (free, unofficial,
occasionally flaky). When a paid feed is worth it, a new module implementing
the same names drops in here and nothing downstream changes.
"""
from __future__ import annotations

from typing import Protocol


class EstimateProvider(Protocol):
    def get_estimates(self, symbol: str) -> dict | None:
        """Current consensus plus whatever revision lookback is available."""
        ...

    def get_earnings_history(self, symbol: str) -> list[dict]:
        """Historical (date, eps_estimate, eps_actual, surprise_pct)."""
        ...


class PriceProvider(Protocol):
    def get_prices(self, symbols: list[str], start: str, end: str): ...


class OptionsProvider(Protocol):
    def get_implied_move(self, symbol: str, after_date: str) -> dict | None: ...


from . import yahoo, nasdaq  # noqa: E402,F401

__all__ = ["yahoo", "nasdaq", "EstimateProvider", "PriceProvider", "OptionsProvider"]
