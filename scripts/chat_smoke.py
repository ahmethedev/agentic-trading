#!/usr/bin/env python
"""One real Claude call through the product tools, printed with its trace.

Run this after putting ANTHROPIC_API_KEY in .env to confirm the chat works
end to end before demoing it -- it is the only script here that spends money.
Reads production records through the same read-only path the API uses; it
cannot place an order or change anything.

    .venv/bin/python scripts/chat_smoke.py "Piyasanın fotoğrafını çıkar"
    .venv/bin/python scripts/chat_smoke.py --operator "Neden işlem açmadık?"

--operator answers as an authenticated operator, which unlocks the account
tools (decisions, risk, fills, run status).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_trade.config import get_settings  # noqa: E402
from agentic_trade.db import pool  # noqa: E402
from agentic_trade.product import llm  # noqa: E402

PRICES = {  # USD per million tokens, for a rough per-question cost
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


async def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--operator"]
    authorized = "--operator" in sys.argv
    question = args[0] if args else "Piyasanın fotoğrafını çıkar"

    settings = get_settings()
    if not llm.available(settings):
        print("ANTHROPIC_API_KEY yok; sohbet deterministik okuyucuya düşer.")
        return 1

    await pool.init_pools(settings.database_url, read_only=True)
    try:
        print(f"> {question}   [operatör: {'açık' if authorized else 'kapalı'}]\n")
        async for event in llm.run(question, settings=settings, authorized=authorized):
            if event["type"] == "text":
                print(event["delta"], end="", flush=True)
            elif event["type"] == "text_reset":
                print("\r" + " " * 80 + "\r", end="")
            elif event["type"] == "tool" and event["phase"] == "start":
                print(f"  · {event['stage']}…")
            elif event["type"] == "tool" and event["phase"] == "end":
                state = "ok" if event["ok"] else "HATA"
                print(f"  · {event['name']} {event['duration_ms']} ms {state}")
            elif event["type"] == "result":
                result = event["result"]
                usage = result.usage
                inp, out = PRICES.get(settings.llm_model, (0.0, 0.0))
                cost = (usage.input_tokens * inp + usage.output_tokens * out) / 1e6
                print(
                    f"\n\n--- {settings.llm_model} · effort {settings.llm_effort}"
                    f" · {result.turns} tur · {len(result.calls)} araç çağrısı"
                    f"\n--- token: {usage.input_tokens} girdi / {usage.output_tokens} çıktı"
                    f" / {usage.cache_read_input_tokens} cache  ≈ ${cost:.4f}"
                    f"\n--- stop_reason: {result.stop_reason}"
                )
    finally:
        await pool.close_pools()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
