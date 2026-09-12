"""Agentic spot trading system for OKX TR."""

# The single source of truth for the version. Read by pyproject (hatchling),
# by the ATK client handshake, by the API, and -- the one that matters -- by
# the worker, which stamps it on every run. `runs.code_version` is how a
# record is tied to the code that produced it, so it must never be a string
# someone forgot to update in one of four places.
__version__ = "0.2.0"
