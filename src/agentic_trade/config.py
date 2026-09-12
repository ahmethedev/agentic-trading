"""Runtime configuration.

Secrets come from the environment (.env); they are never logged or sent to the LLM.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- OKX / ATK ---------------------------------------------------------
    okx_api_key: SecretStr | None = Field(default=None, alias="OKX_API_KEY")
    okx_api_secret: SecretStr | None = Field(default=None, alias="OKX_API_SECRET")
    okx_api_passphrase: SecretStr | None = Field(default=None, alias="OKX_API_PASSPHRASE")
    okx_site: str = Field(default="tr", alias="OKX_SITE")
    okx_demo: bool = Field(default=False, alias="OKX_DEMO")
    # Directory holding the installed @okx_ai/okx-trade-mcp package.
    atk_dir: Path = Field(default=REPO_ROOT / "vendor" / "atk", alias="ATK_DIR")
    atk_timeout_s: float = Field(default=20.0, alias="ATK_TIMEOUT_S")

    # --- Storage -----------------------------------------------------------
    database_url: str = Field(alias="DATABASE_URL")

    # --- Trading mode ------------------------------------------------------
    # observe: no orders at all. paper: simulated fills. live: real orders.
    mode: str = Field(default="observe", alias="MODE")
    quote_ccy: str = Field(default="USDT", alias="QUOTE_CCY")

    # --- Risk (retail_baseline_v1 reference profile) -----------------------
    risk_fraction: Decimal = Field(default=Decimal("0.01"), alias="RISK_FRACTION")
    risk_fraction_max: Decimal = Field(default=Decimal("0.02"), alias="RISK_FRACTION_MAX")
    max_concurrent_positions: int = Field(default=1, alias="MAX_CONCURRENT_POSITIONS")
    # Entries this run may OPEN before the gate stops authorising new ones.
    # 0 = unlimited. Set to 1 for a supervised first live entry: the order goes
    # out, and no second one can follow while attention is elsewhere. Exits and
    # venue-side protection are unaffected -- this caps openings, never closings.
    max_entries_per_run: int = Field(default=0, alias="MAX_ENTRIES_PER_RUN")
    # Instruments an entry may be opened on, comma-separated. Empty = all that
    # are ingested. This narrows TRADING only: market data is still collected for
    # every instrument, so restricting the armed set never blinds the dashboard
    # or interrupts the observe-mode record.
    entry_instruments: str = Field(default="", alias="ENTRY_INSTRUMENTS")

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        allowed = {"observe", "paper", "live"}
        if v not in allowed:
            raise ValueError(f"MODE must be one of {sorted(allowed)}, got {v!r}")
        return v

    @property
    def armed_instruments(self) -> frozenset[str] | None:
        """Instruments entries are allowed on, or None for no restriction."""
        names = {p.strip() for p in self.entry_instruments.split(",") if p.strip()}
        return frozenset(names) or None

    @property
    def has_credentials(self) -> bool:
        """True only when all three OKX secrets are present.

        OKX v5 signs every private request with key + secret + passphrase; two of
        three is not enough for a single authenticated call.
        """
        return all(
            (self.okx_api_key, self.okx_api_secret, self.okx_api_passphrase)
        )

    def atk_env(self) -> dict[str, str]:
        """Environment for the ATK MCP child process.

        Credentials are passed all-or-nothing: ATK aborts at startup with
        ConfigError("Partial API credentials detected.") if only some of the
        three are set, which would kill the whole worker. Until the full set is
        available we run unauthenticated, which still serves every market tool.
        """
        env: dict[str, str] = {"OKX_SITE": self.okx_site}
        if self.okx_demo:
            env["OKX_DEMO"] = "1"
        if self.has_credentials:
            assert self.okx_api_key and self.okx_api_secret and self.okx_api_passphrase
            env["OKX_API_KEY"] = self.okx_api_key.get_secret_value()
            env["OKX_SECRET_KEY"] = self.okx_api_secret.get_secret_value()
            env["OKX_PASSPHRASE"] = self.okx_api_passphrase.get_secret_value()
        return env

    def atk_modules(self) -> str:
        """Modules to start ATK with.

        spot/account tools require auth, so without credentials we ask only for
        market. swap/futures/option are never requested: this is a spot-only
        system and those tools must not exist in the session at all.
        """
        return "market,spot,account" if self.has_credentials else "market"

    def missing_credentials(self) -> list[str]:
        names = {
            "OKX_API_KEY": self.okx_api_key,
            "OKX_API_SECRET": self.okx_api_secret,
            "OKX_API_PASSPHRASE": self.okx_api_passphrase,
        }
        return [k for k, v in names.items() if v is None]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
