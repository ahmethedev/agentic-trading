"""Live venue response-shape invariants that do not call the exchange."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_trade.execution.venue import AtkVenue, VenueRejected


class StubAtk:
    def __init__(self, row: dict) -> None:
        self.row = row

    async def call(self, tool: str, arguments: dict) -> dict:
        assert tool == "spot_place_algo_order"
        return {"data": {"data": [self.row]}}


@pytest.mark.asyncio
async def test_algo_row_rejection_is_not_treated_as_live_protection():
    venue = AtkVenue(StubAtk({"sCode": "51278", "sMsg": "invalid trigger"}))

    with pytest.raises(VenueRejected, match="51278"):
        await venue.place_oco(
            "BTC-USDT",
            Decimal("0.0001"),
            Decimal("78000"),
            Decimal("77000"),
            "cid",
        )


@pytest.mark.asyncio
async def test_algo_row_needs_a_real_venue_id():
    venue = AtkVenue(StubAtk({"sCode": "0", "sMsg": ""}))

    with pytest.raises(VenueRejected, match="ALGO_NO_ID"):
        await venue.place_oco(
            "BTC-USDT",
            Decimal("0.0001"),
            Decimal("78000"),
            Decimal("77000"),
            "cid",
        )
