"""Deterministic position sizing and exit planning.

This module is the risk core (AGENT.md §5). The LLM never calls it and never
overrides its output: it computes quantity from the stop distance, clamps to the
spot balance and venue limits, and freezes the R basis at entry.

Naming discipline -- account risk and price progress are different things:
  * account_r_unit   : 1% of equity, the account-scale R unit
  * risk_budget      : equity * risk_fraction, what this trade may lose
  * price_r_distance : entry - stop, in price terms
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal

# Reference exit plan `retail_baseline_v1`. Percentages are of the INITIAL
# FILLED quantity, never of the remaining quantity.
TP1_R = Decimal("2.0")
TP1_FRACTION = Decimal("0.30")
TP2_R = Decimal("2.5")
TP2_FRACTION = Decimal("0.60")
RUNNER_FRACTION = Decimal("0.10")
BREAKEVEN_R = Decimal("1.0")


class RiskRejection(Exception):
    """Sizing produced no tradeable quantity. Carries the machine-readable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class InstrumentSpec:
    inst_id: str
    lot_sz: Decimal      # quantity step
    min_sz: Decimal      # minimum order size in base
    tick_sz: Decimal     # price step


@dataclass(frozen=True)
class SizingInput:
    equity_quote: Decimal          # net account value in the quote currency
    available_quote: Decimal       # spendable quote balance (spot: the hard cap)
    entry_reference: Decimal
    structural_stop: Decimal
    risk_fraction: Decimal         # default 0.01
    taker_fee_rate: Decimal        # e.g. 0.001 = 10bps, from the venue
    spec: InstrumentSpec
    risk_fraction_max: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class SizingResult:
    quantity: Decimal
    notional: Decimal
    risk_budget: Decimal           # what we were willing to lose
    risk_at_stop: Decimal          # what we actually risk at this quantity
    price_r_distance: Decimal
    account_r_unit: Decimal
    est_cost_per_unit: Decimal
    capped_by: list[str]           # why quantity is below the risk-implied size


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def compute_size(inp: SizingInput) -> SizingResult:
    """Quantity from stop distance, clamped by budget, balance and venue limits.

    Never widens the stop to spend the budget: the risk budget is a ceiling, not
    a target. If the structurally correct stop implies more notional than a spot
    balance supports, the QUANTITY shrinks and the realised risk is reported as
    smaller than the budget.
    """
    if inp.risk_fraction <= 0:
        raise RiskRejection("RISK_FRACTION_NOT_POSITIVE", str(inp.risk_fraction))
    # Hard operational ceiling; adaptation may never lift it silently.
    if inp.risk_fraction > inp.risk_fraction_max:
        raise RiskRejection(
            "RISK_FRACTION_ABOVE_CAP",
            f"{inp.risk_fraction} > {inp.risk_fraction_max}",
        )
    if inp.equity_quote <= 0:
        raise RiskRejection("NO_EQUITY", str(inp.equity_quote))

    price_r = inp.entry_reference - inp.structural_stop
    if price_r <= 0:
        raise RiskRejection("STOP_NOT_BELOW_ENTRY",
                            f"entry={inp.entry_reference} stop={inp.structural_stop}")

    account_r_unit = inp.equity_quote * Decimal("0.01")
    risk_budget = inp.equity_quote * inp.risk_fraction

    # Round-trip taker cost charged against the same unit as the stop distance.
    est_cost_per_unit = inp.entry_reference * inp.taker_fee_rate * 2

    qty_by_risk = risk_budget / (price_r + est_cost_per_unit)

    capped: list[str] = []

    # Spot has no leverage: notional cannot exceed the spendable balance, and we
    # must leave room for the entry fee.
    max_notional = inp.available_quote / (Decimal(1) + inp.taker_fee_rate)
    qty_by_balance = max_notional / inp.entry_reference if inp.entry_reference > 0 else Decimal(0)

    qty = qty_by_risk
    if qty_by_balance < qty:
        qty = qty_by_balance
        capped.append("SPOT_BALANCE")

    qty = _floor_to_step(qty, inp.spec.lot_sz)
    if qty < qty_by_risk:
        capped.append("LOT_STEP")

    if qty <= 0:
        raise RiskRejection("QTY_ROUNDS_TO_ZERO",
                            f"risk-implied {qty_by_risk} below lot {inp.spec.lot_sz}")
    if qty < inp.spec.min_sz:
        # Reaching the venue minimum would require exceeding the risk budget.
        raise RiskRejection(
            "BELOW_MIN_SIZE",
            f"qty {qty} < min {inp.spec.min_sz}; raising it would exceed the risk budget",
        )

    notional = qty * inp.entry_reference
    risk_at_stop = qty * (price_r + est_cost_per_unit)

    # Invariant: realised risk never exceeds the budget (rounding is downward).
    if risk_at_stop > risk_budget:
        raise RiskRejection("RISK_EXCEEDS_BUDGET", f"{risk_at_stop} > {risk_budget}")

    return SizingResult(
        quantity=qty, notional=notional, risk_budget=risk_budget,
        risk_at_stop=risk_at_stop, price_r_distance=price_r,
        account_r_unit=account_r_unit, est_cost_per_unit=est_cost_per_unit,
        capped_by=capped,
    )


# ------------------------------------------------------------------ exits ----
@dataclass(frozen=True)
class ExitPlan:
    """Price triggers and quantities, frozen against the initial filled fill.

    Quantities are fractions of `initial_qty`. Moving the stop to breakeven does
    NOT change the R denominator used for reporting.
    """

    initial_qty: Decimal
    avg_entry_px: Decimal
    initial_stop_px: Decimal
    price_r_distance: Decimal
    breakeven_trigger_px: Decimal
    tp1_trigger_px: Decimal
    tp1_qty: Decimal
    tp2_trigger_px: Decimal
    tp2_qty: Decimal
    runner_qty: Decimal
    frozen_risk_amount: Decimal


def build_exit_plan(
    initial_qty: Decimal,
    avg_entry_px: Decimal,
    initial_stop_px: Decimal,
    spec: InstrumentSpec,
    est_cost_per_unit: Decimal = Decimal(0),
) -> ExitPlan:
    """Build the reference exit ladder from the ACTUAL average entry fill.

    R distance is measured from the real weighted entry, so a bad fill shows up
    as a worse plan rather than being hidden by re-deriving the stop.
    """
    price_r = avg_entry_px - initial_stop_px
    if price_r <= 0:
        raise RiskRejection("STOP_NOT_BELOW_ENTRY",
                            f"entry={avg_entry_px} stop={initial_stop_px}")

    # Sell quantities floor to the lot step so we can never try to sell more
    # base than we own; the runner absorbs the rounding remainder.
    tp1_qty = _floor_to_step(initial_qty * TP1_FRACTION, spec.lot_sz)
    tp2_qty = _floor_to_step(initial_qty * TP2_FRACTION, spec.lot_sz)
    runner_qty = initial_qty - tp1_qty - tp2_qty
    if runner_qty < 0:
        raise RiskRejection("EXIT_QTY_EXCEEDS_POSITION",
                            f"tp1 {tp1_qty} + tp2 {tp2_qty} > {initial_qty}")

    return ExitPlan(
        initial_qty=initial_qty,
        avg_entry_px=avg_entry_px,
        initial_stop_px=initial_stop_px,
        price_r_distance=price_r,
        # Breakeven means the REAL average entry price, gross of fees
        # (AGENT.md §5): net breakeven is a different, separate experiment.
        breakeven_trigger_px=avg_entry_px + price_r * BREAKEVEN_R,
        tp1_trigger_px=avg_entry_px + price_r * TP1_R,
        tp1_qty=tp1_qty,
        tp2_trigger_px=avg_entry_px + price_r * TP2_R,
        tp2_qty=tp2_qty,
        runner_qty=runner_qty,
        frozen_risk_amount=initial_qty * (price_r + est_cost_per_unit),
    )


def round_price(px: Decimal, spec: InstrumentSpec, *, up: bool = False) -> Decimal:
    if spec.tick_sz <= 0:
        return px
    rounding = ROUND_UP if up else ROUND_DOWN
    return (px / spec.tick_sz).to_integral_value(rounding=rounding) * spec.tick_sz
