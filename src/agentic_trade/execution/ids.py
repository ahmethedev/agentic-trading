"""Client order id generation.

OKX accepts 1-32 alphanumeric characters for `clOrdId` / `algoClOrdId`. The id is
our idempotency key: it is written to the ledger BEFORE the order is sent, so a
timeout can be resolved by querying the venue for this exact id instead of
resending blind.

A client id is not an unlimited idempotency guarantee (AGENT.md §5): the venue may
expire or reject ids, so it is a reconciliation handle, not a licence to resend.
"""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits
MAX_LEN = 32


def _b36(n: int) -> str:
    if n == 0:
        return "0"
    out: list[str] = []
    while n:
        n, r = divmod(n, 36)
        out.append(_ALPHABET[r])
    return "".join(reversed(out))


def new_client_order_id(intent_id: int, purpose: str) -> str:
    """Build a unique, venue-legal client order id.

    Layout: at<intent_b36>{purpose-tag}{random}. The intent id makes the order
    traceable in the ledger; the random tail keeps retries after a *definitive*
    rejection from colliding with the original id.
    """
    tag = {
        "ENTRY": "e", "STOP": "s", "TP1": "a", "TP2": "b",
        "RUNNER_EXIT": "r", "FLATTEN": "f",
    }.get(purpose, "x")
    head = f"at{_b36(intent_id)}{tag}"
    tail_len = MAX_LEN - len(head)
    if tail_len < 4:
        raise ValueError(f"intent_id {intent_id} too large for a 32-char clOrdId")
    tail = "".join(secrets.choice(_ALPHABET) for _ in range(min(tail_len, 8)))
    cid = f"{head}{tail}"
    assert cid.isalnum() and len(cid) <= MAX_LEN
    return cid
