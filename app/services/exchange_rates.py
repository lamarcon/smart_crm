"""Automatic BRL exchange rates from the Banco Central do Brasil PTAX bulletin.

Deals may be priced in USD or EUR. Their value in BRL follows the official
PTAX closing rate (selling side), fetched from the BCB open-data API, so nobody
has to type an exchange rate by hand. Rates are cached in memory and refreshed
hourly; when the BCB is unreachable the last good rate is kept and flagged as
stale, so the CRM never blocks on the external service.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Protocol


BASE_CURRENCY = "BRL"
FOREIGN_CURRENCIES = ("USD", "EUR")
SUPPORTED_CURRENCIES = (BASE_CURRENCY, *FOREIGN_CURRENCIES)

PTAX_ENDPOINT = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
CLOSING_BULLETIN = "Fechamento"
LOOKBACK_DAYS = 10
# A closing rate older than this (long holiday, outage) is still used but flagged.
STALE_AFTER = timedelta(days=5)


class ExchangeRateUnavailable(RuntimeError):
    """The PTAX closing rate could not be obtained."""


@dataclass(frozen=True)
class ExchangeRate:
    currency: str
    rate: Decimal
    date: date


@dataclass(frozen=True)
class ExchangeRateSnapshot:
    rates: dict[str, ExchangeRate]
    fetched_at: datetime | None
    stale: bool


class ClosingRateSource(Protocol):
    def latest_closing(self, currency: str, today: date) -> ExchangeRate: ...


def _fetch_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SmartCRM"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))


class PtaxClient:
    """Reads the latest PTAX closing bulletin of a currency from the BCB API."""

    def __init__(
        self,
        fetch: Callable[[str, float], dict] = _fetch_json,
        timeout_seconds: float = 6.0,
    ) -> None:
        self._fetch = fetch
        self._timeout = timeout_seconds

    def url(self, currency: str, today: date) -> str:
        start = today - timedelta(days=LOOKBACK_DAYS)
        query = urllib.parse.urlencode(
            {
                "@moeda": f"'{currency}'",
                "@dataInicial": f"'{start:%m-%d-%Y}'",
                "@dataFinalCotacao": f"'{today:%m-%d-%Y}'",
                "$format": "json",
                "$select": "cotacaoVenda,dataHoraCotacao,tipoBoletim",
            },
            safe="@'$-",
        )
        return f"{PTAX_ENDPOINT}?{query}"

    def latest_closing(self, currency: str, today: date) -> ExchangeRate:
        if currency not in FOREIGN_CURRENCIES:
            raise ExchangeRateUnavailable(f"unsupported currency {currency}")
        try:
            payload = self._fetch(self.url(currency, today), self._timeout)
        except Exception as error:  # network, TLS, HTTP or JSON failure
            raise ExchangeRateUnavailable("ptax request failed") from error
        items = payload.get("value") if isinstance(payload, dict) else None
        closings: list[tuple[str, Decimal]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get("tipoBoletim") != CLOSING_BULLETIN:
                continue
            try:
                rate = Decimal(str(item["cotacaoVenda"]))
                stamp = str(item["dataHoraCotacao"])
                date.fromisoformat(stamp[:10])
            except (KeyError, InvalidOperation, ValueError):
                continue
            if rate > 0:
                closings.append((stamp, rate))
        if not closings:
            raise ExchangeRateUnavailable("no ptax closing bulletin in range")
        stamp, rate = max(closings)
        return ExchangeRate(currency=currency, rate=rate, date=date.fromisoformat(stamp[:10]))


class ExchangeRateService:
    """Thread-safe, self-refreshing cache of the PTAX closing rates."""

    def __init__(
        self,
        source: ClosingRateSource | None = None,
        clock: Callable[[], datetime] | None = None,
        refresh_interval: timedelta = timedelta(hours=1),
        retry_interval: timedelta = timedelta(minutes=5),
    ) -> None:
        self._source = source or PtaxClient()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._refresh_interval = refresh_interval
        self._retry_interval = retry_interval
        self._lock = threading.Lock()
        self._rates: dict[str, ExchangeRate] = {}
        self._fetched_at: datetime | None = None
        self._last_attempt: datetime | None = None
        self._last_failed = False

    def _due(self, now: datetime) -> bool:
        if self._last_attempt is None:
            return True
        wait = self._retry_interval if self._last_failed else self._refresh_interval
        return now - self._last_attempt >= wait

    def _refresh(self, now: datetime) -> None:
        self._last_attempt = now
        failed = False
        today = now.astimezone(timezone(timedelta(hours=-3))).date()
        for currency in FOREIGN_CURRENCIES:
            try:
                self._rates[currency] = self._source.latest_closing(currency, today)
            except ExchangeRateUnavailable:
                failed = True
        if not failed:
            self._fetched_at = now
        self._last_failed = failed

    def snapshot(self) -> ExchangeRateSnapshot:
        with self._lock:
            now = self._clock()
            if self._due(now):
                self._refresh(now)
            rates = dict(self._rates)
            today = now.astimezone(timezone(timedelta(hours=-3))).date()
            outdated = any(today - rate.date > STALE_AFTER for rate in rates.values())
            stale = self._last_failed or outdated or len(rates) != len(FOREIGN_CURRENCIES)
            return ExchangeRateSnapshot(rates=rates, fetched_at=self._fetched_at, stale=stale)

    def rate_for(self, currency: str) -> ExchangeRate | None:
        """Rate to convert one unit of ``currency`` into BRL (None if unknown)."""

        if currency == BASE_CURRENCY:
            return ExchangeRate(currency=BASE_CURRENCY, rate=Decimal("1"), date=self._clock().date())
        return self.snapshot().rates.get(currency)


def snapshot_payload(snapshot: ExchangeRateSnapshot) -> dict:
    return {
        "base": BASE_CURRENCY,
        "rates": {
            currency: {"rate": str(rate.rate), "date": rate.date.isoformat()}
            for currency, rate in sorted(snapshot.rates.items())
        },
        "source": "PTAX/BCB",
        "stale": snapshot.stale,
        "fetchedAt": snapshot.fetched_at.isoformat().replace("+00:00", "Z") if snapshot.fetched_at else None,
    }
