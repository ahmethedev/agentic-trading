"""Venue adapters.

One protocol, two implementations, so the order state machine is identical in
paper and live. The paper venue can inject exactly the failures AGENT.md §11
requires us to survive -- timeout, partial fill, duplicate fill, late ack,
cancel/fill race -- none of which can be provoked on demand against a real venue.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from ..atk.client import AtkClient, AtkError, AtkTimeout


class OrdStatus(StrEnum):
    LIVE = "live"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


TERMINAL = {OrdStatus.FILLED, OrdStatus.CANCELED, OrdStatus.REJECTED}


@dataclass
class Fill:
    fill_id: str
    client_order_id: str
    exchange_order_id: str
    inst_id: str
    side: str
    px: Decimal
    qty: Decimal
    fee: Decimal
    fee_ccy: str
    liquidity: str
    ts: datetime


@dataclass
class OrderState:
    client_order_id: str
    exchange_order_id: str | None
    inst_id: str
    side: str
    status: OrdStatus
    qty_requested: Decimal
    qty_filled: Decimal
    avg_px: Decimal | None
    raw: dict | None = None


class VenueUnknown(RuntimeError):
    """The request's outcome is not known. The order may or may not exist."""


class VenueRejected(RuntimeError):
    """The venue definitively refused the request. Safe not to retry blindly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Venue(Protocol):
    async def place_limit_ioc(
        self, inst_id: str, side: str, qty: Decimal, px_limit: Decimal,
        client_order_id: str,
    ) -> OrderState: ...

    async def get_order(
        self, inst_id: str, client_order_id: str
    ) -> OrderState: ...

    async def cancel_order(self, inst_id: str, client_order_id: str) -> None: ...

    async def get_fills(
        self,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> list[Fill]: ...

    async def place_oco(
        self, inst_id: str, qty: Decimal, tp_trigger: Decimal, sl_trigger: Decimal,
        client_order_id: str,
    ) -> str: ...

    async def get_balances(self) -> dict[str, Decimal]: ...

    async def get_open_orders(self, inst_id: str | None = None) -> list[OrderState]: ...

    async def get_algo_orders(self, inst_id: str) -> list[dict]: ...


# ----------------------------------------------------------------- live ------
class AtkVenue:
    """Live adapter over the ATK MCP session."""

    def __init__(self, atk: AtkClient) -> None:
        self._atk = atk

    async def place_limit_ioc(
        self, inst_id: str, side: str, qty: Decimal, px_limit: Decimal,
        client_order_id: str,
    ) -> OrderState:
        # ordType=ioc keeps `sz` in BASE currency. Only a *market buy* switches
        # sz to quote, which is why this path never uses ordType=market.
        args = {
            "instId": inst_id, "tdMode": "cash", "side": side, "ordType": "ioc",
            "sz": str(qty), "px": str(px_limit), "clOrdId": client_order_id,
            "tgtCcy": "base_ccy",
        }
        try:
            payload = await self._atk.call("spot_place_order", args)
        except AtkTimeout as exc:
            raise VenueUnknown(f"place timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueRejected("PLACE_FAILED", str(exc)) from exc
        row = payload["data"]["data"][0]
        return OrderState(
            client_order_id=client_order_id,
            exchange_order_id=row.get("ordId") or None,
            inst_id=inst_id, side=side, status=OrdStatus.LIVE,
            qty_requested=qty, qty_filled=Decimal(0), avg_px=None, raw=row,
        )

    async def get_order(self, inst_id: str, client_order_id: str) -> OrderState:
        try:
            payload = await self._atk.call(
                "spot_get_order", {"instId": inst_id, "clOrdId": client_order_id}
            )
        except AtkTimeout as exc:
            raise VenueUnknown(f"get_order timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueUnknown(f"get_order failed: {exc}") from exc
        rows = payload["data"]["data"]
        if not rows:
            # No record: the order never reached the matching engine, but a
            # just-sent order can also be briefly invisible. Caller decides.
            return OrderState(client_order_id, None, inst_id, "", OrdStatus.UNKNOWN,
                              Decimal(0), Decimal(0), None)
        r = rows[0]
        filled = Decimal(r.get("accFillSz") or 0)
        avg = Decimal(r["avgPx"]) if r.get("avgPx") else None
        return OrderState(
            client_order_id=client_order_id,
            exchange_order_id=r.get("ordId"),
            inst_id=inst_id, side=r.get("side", ""),
            status=_map_status(r.get("state", "")),
            qty_requested=Decimal(r.get("sz") or 0),
            qty_filled=filled, avg_px=avg, raw=r,
        )

    async def cancel_order(self, inst_id: str, client_order_id: str) -> None:
        try:
            await self._atk.call(
                "spot_cancel_order", {"instId": inst_id, "clOrdId": client_order_id}
            )
        except AtkTimeout as exc:
            # Cancelling is not confirmed; the order may still fill.
            raise VenueUnknown(f"cancel timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueRejected("CANCEL_FAILED", str(exc)) from exc

    async def get_fills(
        self,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> list[Fill]:
        args: dict = {"instId": inst_id, "limit": 100}
        # The unfiltered endpoint is only the most recent 100 fills.  Once we
        # know the venue order id, ask for that order directly so a restart can
        # still repair an older ledger gap and cannot lose the row behind newer
        # activity on the same instrument.
        if exchange_order_id:
            args["ordId"] = exchange_order_id
        try:
            payload = await self._atk.call("spot_get_fills", args)
        except AtkTimeout as exc:
            raise VenueUnknown(f"get_fills timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueUnknown(f"get_fills failed: {exc}") from exc
        out: list[Fill] = []
        for r in payload["data"]["data"]:
            if client_order_id and r.get("clOrdId") != client_order_id:
                continue
            out.append(Fill(
                fill_id=str(r.get("tradeId") or r.get("billId")),
                client_order_id=r.get("clOrdId") or "",
                exchange_order_id=r.get("ordId") or "",
                inst_id=r.get("instId", inst_id), side=r.get("side", ""),
                px=Decimal(r["fillPx"]), qty=Decimal(r["fillSz"]),
                # OKX reports fee negative as a cost; store the magnitude paid.
                fee=abs(Decimal(r.get("fee") or 0)),
                fee_ccy=r.get("feeCcy", ""),
                liquidity=r.get("execType", ""),
                ts=datetime.fromtimestamp(int(r["ts"]) / 1000, tz=UTC),
            ))
        return out

    async def place_oco(
        self, inst_id: str, qty: Decimal, tp_trigger: Decimal, sl_trigger: Decimal,
        client_order_id: str,
    ) -> str:
        # No tgtCcy here. It is valid on spot_place_order but NOT on the algo
        # endpoint, which rejects the whole request with 51000 "Parameter tgtCcy
        # error" -- and an OCO that is never accepted is a position with no stop.
        # `sz` on a spot algo order is always base, which is what we want anyway.
        args = {
            "instId": inst_id, "tdMode": "cash", "side": "sell", "ordType": "oco",
            "sz": str(qty), "tpTriggerPx": str(tp_trigger), "tpOrdPx": "-1",
            "slTriggerPx": str(sl_trigger), "slOrdPx": "-1",
            "algoClOrdId": client_order_id,
        }
        try:
            payload = await self._atk.call("spot_place_algo_order", args)
        except AtkTimeout as exc:
            raise VenueUnknown(f"place_oco timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueRejected("ALGO_FAILED", str(exc)) from exc
        row = payload["data"]["data"][0]
        # OKX uses HTTP/code=0 for an accepted batch request even when the
        # individual algo row was rejected. ATK therefore returns a normal
        # payload whose row has sCode/sMsg but no algoId. Treating that as
        # success writes a fake live STOP and leaves the position naked.
        row_code = str(row.get("sCode") or "")
        algo_id = str(row.get("algoId") or "")
        if row_code not in ("", "0") or not algo_id:
            message = str(row.get("sMsg") or "venue returned no algoId")
            error_code = row_code if row_code not in ("", "0") else "ALGO_NO_ID"
            raise VenueRejected(error_code, message)
        return algo_id


    async def get_balances(self) -> dict[str, Decimal]:
        """Available balance per currency, as the venue sees it.

        This is ground truth for reconciliation: the local ledger can be wrong,
        the exchange's view of what we hold cannot.
        """
        try:
            payload = await self._atk.call("account_get_balance", {})
        except AtkTimeout as exc:
            raise VenueUnknown(f"get_balances timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueUnknown(f"get_balances failed: {exc}") from exc
        out: dict[str, Decimal] = {}
        rows = payload["data"]["data"]
        if not rows:
            return out
        for d in rows[0].get("details") or []:
            # availBal excludes amounts locked by resting orders; eq is the total.
            out[d["ccy"]] = Decimal(d.get("eq") or 0)
        return out

    async def get_open_orders(self, inst_id: str | None = None) -> list[OrderState]:
        args: dict = {"status": "open"}
        if inst_id:
            args["instId"] = inst_id
        try:
            payload = await self._atk.call("spot_get_orders", args)
        except AtkTimeout as exc:
            raise VenueUnknown(f"get_open_orders timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueUnknown(f"get_open_orders failed: {exc}") from exc
        out = []
        for r in payload["data"]["data"]:
            out.append(OrderState(
                client_order_id=r.get("clOrdId") or "",
                exchange_order_id=r.get("ordId"),
                inst_id=r.get("instId", ""), side=r.get("side", ""),
                status=_map_status(r.get("state", "")),
                qty_requested=Decimal(r.get("sz") or 0),
                qty_filled=Decimal(r.get("accFillSz") or 0),
                avg_px=Decimal(r["avgPx"]) if r.get("avgPx") else None, raw=r,
            ))
        return out

    async def get_algo_orders(self, inst_id: str) -> list[dict]:
        """Pending TP/SL (algo) orders -- i.e. whether protection is still live."""
        try:
            payload = await self._atk.call(
                "spot_get_algo_orders", {"instId": inst_id, "ordType": "oco"})
        except AtkTimeout as exc:
            raise VenueUnknown(f"get_algo_orders timed out: {exc}") from exc
        except AtkError as exc:
            raise VenueUnknown(f"get_algo_orders failed: {exc}") from exc
        return payload["data"]["data"]


def _map_status(state: str) -> OrdStatus:
    return {
        "live": OrdStatus.LIVE,
        "partially_filled": OrdStatus.PARTIALLY_FILLED,
        "filled": OrdStatus.FILLED,
        "canceled": OrdStatus.CANCELED,
        "cancelled": OrdStatus.CANCELED,
        "mmp_canceled": OrdStatus.CANCELED,
    }.get(state, OrdStatus.UNKNOWN)


# ---------------------------------------------------------------- paper ------
@dataclass
class Faults:
    """Deterministic fault injection for tests."""

    place_timeout: bool = False        # place() raises VenueUnknown but DOES place
    place_reject: str | None = None    # place() raises VenueRejected
    cancel_timeout: bool = False       # cancel raises, yet the order still fills
    fill_ratio: Decimal = Decimal(1)   # portion of qty that fills
    duplicate_fills: bool = False      # same fill reported twice
    get_order_timeout: bool = False
    balances_timeout: bool = False


@dataclass
class PaperVenue:
    """In-memory venue with the same contract as the live one."""

    fee_rate: Decimal = Decimal("0.001")
    faults: Faults = field(default_factory=Faults)
    _orders: dict[str, OrderState] = field(default_factory=dict)
    _fills: dict[str, list[Fill]] = field(default_factory=dict)
    _algos: dict[str, list[dict]] = field(default_factory=dict)
    balances: dict[str, Decimal] = field(default_factory=dict)
    _seq: int = 0
    placed_calls: int = 0
    # Per-instance prefix: ids must stay unique across runs, since they are
    # stored under a UNIQUE (venue, exchange_order_id) constraint just like
    # real venue ids.
    _prefix: str = field(default_factory=lambda: secrets.token_hex(4))

    def _next(self, p: str) -> str:
        self._seq += 1
        return f"{p}{self._prefix}{self._seq}"

    async def place_limit_ioc(
        self, inst_id: str, side: str, qty: Decimal, px_limit: Decimal,
        client_order_id: str,
    ) -> OrderState:
        self.placed_calls += 1
        if self.faults.place_reject:
            raise VenueRejected(self.faults.place_reject, "paper rejection")

        exch = self._next("ord")
        filled = (qty * self.faults.fill_ratio).quantize(Decimal("0.00000001"))
        status = (
            OrdStatus.FILLED if filled == qty
            else OrdStatus.CANCELED if filled > 0   # IOC: unfilled part is cancelled
            else OrdStatus.CANCELED
        )
        st = OrderState(client_order_id, exch, inst_id, side, status, qty, filled,
                        px_limit if filled > 0 else None)
        self._orders[client_order_id] = st
        if filled > 0:
            base, quote = inst_id.split("-", 1)
            # OKX charges the spot fee in the currency you RECEIVE: a buy pays
            # in base, a sell pays in quote. Modelling a buy fee in quote was
            # what hid a live incident -- protection was sized to the filled
            # quantity, but the fee had already been taken out of the base, so
            # the OCO was rejected for insufficient balance and the position sat
            # naked. The simulator must charge it the same way the venue does.
            if side == "buy":
                fee, fee_ccy = filled * self.fee_rate, base
                self._credit(base, filled - fee)
                self._credit(quote, -(filled * px_limit))
            else:
                fee, fee_ccy = filled * px_limit * self.fee_rate, quote
                self._credit(base, -filled)
                self._credit(quote, filled * px_limit - fee)
            f = Fill(self._next("fill"), client_order_id, exch, inst_id, side,
                     px_limit, filled, fee, fee_ccy, "T", datetime.now(UTC))
            self._fills.setdefault(client_order_id, []).append(f)
            if self.faults.duplicate_fills:
                self._fills[client_order_id].append(f)   # same fill_id twice

        if self.faults.place_timeout:
            # The order IS live at the venue, but the caller never learns the id.
            raise VenueUnknown("paper: place timed out after reaching the venue")
        return st

    async def get_order(self, inst_id: str, client_order_id: str) -> OrderState:
        if self.faults.get_order_timeout:
            raise VenueUnknown("paper: get_order timed out")
        st = self._orders.get(client_order_id)
        if st is None:
            return OrderState(client_order_id, None, inst_id, "", OrdStatus.UNKNOWN,
                              Decimal(0), Decimal(0), None)
        return st

    async def cancel_order(self, inst_id: str, client_order_id: str) -> None:
        if self.faults.cancel_timeout:
            raise VenueUnknown("paper: cancel timed out")
        st = self._orders.get(client_order_id)
        if st and st.status not in TERMINAL:
            st.status = OrdStatus.CANCELED

    async def get_fills(
        self,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> list[Fill]:
        if client_order_id:
            return list(self._fills.get(client_order_id, []))
        return [f for fs in self._fills.values() for f in fs]

    async def place_oco(
        self, inst_id: str, qty: Decimal, tp_trigger: Decimal, sl_trigger: Decimal,
        client_order_id: str,
    ) -> str:
        await asyncio.sleep(0)
        # A protective sell is a real sell: the venue rejects it outright if the
        # base is not actually held. Simulating an always-successful OCO is what
        # let an unsellable size reach production.
        base = inst_id.split("-", 1)[0]
        held = self.balances.get(base, Decimal(0))
        if qty > held:
            raise VenueRejected(
                "ALGO_FAILED",
                f"paper: insufficient {base} balance, have {held}, asked {qty}")
        algo_id = self._next("algo")
        self._algos.setdefault(inst_id, []).append(
            {"algoId": algo_id, "algoClOrdId": client_order_id, "sz": str(qty),
             "state": "live"})
        return algo_id

    def _credit(self, ccy: str, amount: Decimal) -> None:
        self.balances[ccy] = self.balances.get(ccy, Decimal(0)) + amount

    async def get_balances(self) -> dict[str, Decimal]:
        if self.faults.balances_timeout:
            raise VenueUnknown("paper: get_balances timed out")
        return {k: v for k, v in self.balances.items() if v != 0}

    async def get_open_orders(self, inst_id: str | None = None) -> list[OrderState]:
        return [o for o in self._orders.values()
                if o.status not in TERMINAL
                and (inst_id is None or o.inst_id == inst_id)]

    async def get_algo_orders(self, inst_id: str) -> list[dict]:
        return list(self._algos.get(inst_id, []))
