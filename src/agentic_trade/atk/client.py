"""Persistent stdio MCP client for the OKX Agent Trade Kit.

Design constraints (AGENT.md §7):
  * One long-lived ATK process per worker -- never spawn per tick.
  * Tool-level allowlist. Selecting a module is NOT a substitute for restricting
    individual tools: `--modules spot` alone would still expose batch order tools.
  * A call timeout means the OUTCOME IS UNKNOWN, not that the exchange rejected
    or cancelled anything. Write callers must reconcile, never blindly resend.
  * Secrets are passed through the child environment only; they never appear in
    logs, exceptions, or LLM-visible text.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# --- Allowlist ---------------------------------------------------------------
# Read-only tools: safe for the agent and for deterministic polling.
READ_TOOLS: frozenset[str] = frozenset({
    "market_get_ticker",
    "market_get_tickers",
    "market_get_orderbook",
    "market_get_candles",
    "market_get_trades",
    "market_get_instruments",
    "account_get_balance",
    "account_get_asset_balance",
    "account_get_balance_all",
    "account_get_trade_fee",
    "account_get_config",
    "account_get_bills",
    "spot_get_order",
    "spot_get_orders",
    "spot_get_fills",
    "spot_get_algo_orders",
    "system_get_capabilities",
})

# Write tools: reachable ONLY from the order manager, after risk checks and a
# durable intent + reservation. Never exposed to the LLM.
WRITE_TOOLS: frozenset[str] = frozenset({
    "spot_place_order",
    "spot_cancel_order",
    "spot_amend_order",
    "spot_place_algo_order",
    "spot_cancel_algo_order",
    "spot_amend_algo_order",
})

ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS

# Modules the server is started with. swap/futures/option are excluded entirely:
# the competition is spot-only, so those tools must not exist in the session.
ATK_MODULES = "market,spot,account"

# Max bytes for a single JSON-RPC line from ATK (default asyncio limit is 64KiB).
STDOUT_LINE_LIMIT = 16 * 1024 * 1024


class AtkError(RuntimeError):
    """The exchange or the ATK server returned a definitive error."""


class AtkTimeout(RuntimeError):
    """No response within the deadline. The outcome is UNKNOWN.

    For write calls the order may still have reached the exchange. The caller
    must reconcile via spot_get_order / spot_get_fills before any resend.
    """


class AtkNotRunning(RuntimeError):
    """The ATK process is not available."""


@dataclass
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class AtkClient:
    """Long-lived JSON-RPC (MCP over stdio) client for one ATK process."""

    def __init__(
        self,
        atk_dir: os.PathLike[str] | str,
        env: dict[str, str],
        *,
        timeout_s: float = 20.0,
        read_only: bool = False,
        modules: str = ATK_MODULES,
    ) -> None:
        self._atk_dir = os.fspath(atk_dir)
        self._env = env
        self._timeout_s = timeout_s
        self._read_only = read_only
        self._modules = modules

        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._tools: dict[str, ToolSchema] = {}
        self._server_info: dict[str, Any] = {}

    # --- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        entry = os.path.join(
            self._atk_dir, "node_modules", "@okx_ai", "okx-trade-mcp", "dist", "index.js"
        )
        if not os.path.exists(entry):
            raise AtkNotRunning(
                f"ATK entrypoint missing: {entry} (run `npm install` in vendor/atk)"
            )

        args = [entry, "--modules", self._modules]
        if self._read_only:
            args.append("--read-only")

        # Minimal environment: PATH/HOME for node, plus the OKX settings.
        child_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "OKX_UPDATE_CHECK": "0",
            **self._env,
        }
        self._proc = await asyncio.create_subprocess_exec(
            "node", *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
            # One JSON-RPC message per line. A 500-print market_get_trades reply
            # is ~90KB, well past asyncio's 64KiB default, which would otherwise
            # raise LimitOverrunError and tear down the session.
            limit=STDOUT_LINE_LIMIT,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

        init = await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentic-trade", "version": "0.1.0"},
            },
        )
        self._server_info = init.get("serverInfo", {})
        await self._notify("notifications/initialized")

        listed = await self._request("tools/list", {})
        for t in listed.get("tools", []):
            self._tools[t["name"]] = ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
        log.info(
            "atk.started",
            server=self._server_info.get("name"),
            version=self._server_info.get("version"),
            tools_exposed=len(self._tools),
            modules=self._modules,
            read_only=self._read_only,
        )

    async def stop(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                self._proc.kill()
        self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def tools(self) -> dict[str, ToolSchema]:
        return dict(self._tools)

    # --- transport --------------------------------------------------------
    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = msg.get("id")
            if mid is None:
                continue
            fut = self._pending.pop(mid, None)
            if fut and not fut.done():
                fut.set_result(msg)
        # stdout closed: fail everything still waiting -- outcome UNKNOWN.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(AtkTimeout("ATK process exited while awaiting response"))
        self._pending.clear()

    async def _stderr_loop(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if text:
                log.debug("atk.stderr", line=text[:500])

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise AtkNotRunning("ATK process is not running")
        async with self._write_lock:
            self._proc.stdin.write(json.dumps(payload).encode() + b"\n")
            await self._proc.stdin.drain()

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _request(
        self, method: str, params: dict[str, Any], timeout_s: float | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        rid = self._next_id
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            msg = await asyncio.wait_for(fut, timeout=timeout_s or self._timeout_s)
        except TimeoutError as exc:
            self._pending.pop(rid, None)
            raise AtkTimeout(f"{method} timed out after {timeout_s or self._timeout_s}s") from exc
        if "error" in msg:
            err = msg["error"]
            raise AtkError(f"{method}: {err.get('code')} {err.get('message')}")
        return msg.get("result", {})

    # --- tool calls -------------------------------------------------------
    async def call(
        self, tool: str, arguments: dict[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """Call an allowlisted ATK tool and return the parsed payload.

        Raises AtkTimeout (outcome UNKNOWN) or AtkError (definitive failure).
        """
        if tool not in ALLOWED_TOOLS:
            raise AtkError(f"tool {tool!r} is not allowlisted")
        if tool not in self._tools:
            raise AtkError(f"tool {tool!r} not exposed by this ATK session")

        result = await self._request(
            "tools/call", {"name": tool, "arguments": arguments}, timeout_s=timeout_s
        )
        return self._parse_payload(tool, result)

    @staticmethod
    def _parse_payload(tool: str, result: dict[str, Any]) -> dict[str, Any]:
        content = result.get("content") or []
        if not content:
            raise AtkError(f"{tool}: empty response content")
        text = content[0].get("text", "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AtkError(f"{tool}: non-JSON response") from exc

        if payload.get("ok") is False or result.get("isError"):
            # Surface the venue error code so callers can distinguish a permanent
            # rejection (bad size/balance) from a transient one worth retrying.
            #
            # ATK reports failures as {"error": true, type, code, message, ...}.
            # Reading `error` as the description turned every rejection into the
            # string "true" -- which is how an OCO refused for insufficient
            # balance reached the ledger as "ALGO_FAILED: true" and cost hours of
            # diagnosis. Build the message from the fields that carry meaning.
            raise AtkError(f"{tool}: {_describe_error(payload)}")
        return payload


def _describe_error(payload: dict[str, Any]) -> str:
    """A human- and grep-readable description of an ATK/OKX failure."""
    err = payload.get("error")
    # Older/other shapes put the description in `error` itself; the current ATK
    # puts a bare `true` there and the meaning in the sibling fields.
    if isinstance(err, dict):
        return json.dumps(err)[:400]
    if isinstance(err, str) and err:
        return err[:400]
    parts = [
        str(payload[k]) for k in ("type", "code", "message", "suggestion")
        if payload.get(k)
    ]
    if parts:
        return " | ".join(parts)[:400]
    return json.dumps(payload)[:400]
