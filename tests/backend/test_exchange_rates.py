from __future__ import annotations

import urllib.parse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import ResolvedPrincipal
from app.main import create_app
from app.services.exchange_rates import (
    ExchangeRate,
    ExchangeRateService,
    ExchangeRateUnavailable,
    PtaxClient,
    snapshot_payload,
)
from tests.backend.test_api import TEST_SESSION_CONTEXT, FakeDatabase


def bulletin(stamp: str, sell: float, kind: str = "Fechamento") -> dict:
    return {"cotacaoCompra": sell - 0.0006, "cotacaoVenda": sell, "dataHoraCotacao": stamp, "tipoBoletim": kind}


# --- PTAX client ----------------------------------------------------------------


def test_ptax_url_asks_the_last_ten_days_of_one_currency() -> None:
    url = PtaxClient().url("USD", date(2026, 11, 12))
    assert url.startswith("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo(")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["@moeda"] == ["'USD'"]
    assert query["@dataInicial"] == ["'11-02-2026'"]
    assert query["@dataFinalCotacao"] == ["'11-12-2026'"]
    assert query["$format"] == ["json"]


def test_ptax_uses_the_latest_closing_selling_rate_only() -> None:
    payload = {"value": [
        bulletin("2026-11-10 13:06:01.35", 5.51),
        bulletin("2026-11-11 10:04:00.00", 5.70, "Abertura"),
        bulletin("2026-11-11 13:02:30.35", 5.5606),
        bulletin("2026-11-12 11:00:00.00", 5.80, "Intermediário"),
    ]}
    client = PtaxClient(fetch=lambda url, timeout: payload)
    assert client.latest_closing("USD", date(2026, 11, 12)) == ExchangeRate("USD", Decimal("5.5606"), date(2026, 11, 11))


def test_ptax_over_a_weekend_returns_fridays_closing() -> None:
    payload = {"value": [bulletin("2026-11-06 13:06:13.96", 6.1317)]}
    rate = PtaxClient(fetch=lambda url, timeout: payload).latest_closing("EUR", date(2026, 11, 8))
    assert (rate.rate, rate.date) == (Decimal("6.1317"), date(2026, 11, 6))


@pytest.mark.parametrize(
    "payload",
    [
        {"value": []},
        {"value": [bulletin("2026-11-11 11:00:00", 5.6, "Intermediário")]},
        {"value": [{"tipoBoletim": "Fechamento", "cotacaoVenda": "x", "dataHoraCotacao": "2026-11-11"}]},
        {"value": [bulletin("2026-11-11 13:00:00", 0)]},
        {"value": "nada"},
        ["lista"],
        {},
    ],
)
def test_ptax_without_a_usable_closing_is_unavailable(payload) -> None:  # noqa: ANN001
    with pytest.raises(ExchangeRateUnavailable):
        PtaxClient(fetch=lambda url, timeout: payload).latest_closing("USD", date(2026, 11, 12))


def test_ptax_network_failure_is_unavailable() -> None:
    def broken(url, timeout):  # noqa: ANN001, ANN202
        raise OSError("timed out")

    with pytest.raises(ExchangeRateUnavailable):
        PtaxClient(fetch=broken).latest_closing("USD", date(2026, 11, 12))


def test_ptax_refuses_unsupported_currencies_without_calling_the_bcb() -> None:
    def never(url, timeout):  # noqa: ANN001, ANN202
        raise AssertionError("should not call")

    with pytest.raises(ExchangeRateUnavailable):
        PtaxClient(fetch=never).latest_closing("GBP", date(2026, 11, 12))


# --- Cached service ---------------------------------------------------------------


class FakeSource:
    def __init__(self) -> None:
        self.rates = {"USD": Decimal("5.5606"), "EUR": Decimal("6.1706")}
        self.day = date(2026, 11, 11)
        self.calls: list[tuple[str, date]] = []
        self.down = False

    def latest_closing(self, currency: str, today: date) -> ExchangeRate:
        self.calls.append((currency, today))
        if self.down:
            raise ExchangeRateUnavailable("down")
        return ExchangeRate(currency, self.rates[currency], self.day)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def test_service_fetches_once_and_reuses_the_rates_within_the_hour() -> None:
    source, clock = FakeSource(), Clock()
    service = ExchangeRateService(source=source, clock=clock)
    first = service.snapshot()
    assert {k: v.rate for k, v in first.rates.items()} == {"USD": Decimal("5.5606"), "EUR": Decimal("6.1706")}
    assert first.stale is False
    assert [currency for currency, _day in source.calls] == ["USD", "EUR"]
    # Brazilian date is used for the lookup (UTC 13:00 is 10:00 in Brasília).
    assert source.calls[0][1] == date(2026, 11, 12)
    clock.now += timedelta(minutes=59)
    service.snapshot()
    assert len(source.calls) == 2


def test_service_refreshes_hourly_and_picks_up_the_new_closing() -> None:
    source, clock = FakeSource(), Clock()
    service = ExchangeRateService(source=source, clock=clock)
    service.snapshot()
    source.rates["USD"], source.day = Decimal("5.60"), date(2026, 11, 12)
    clock.now += timedelta(hours=1)
    rate = service.rate_for("USD")
    assert (rate.rate, rate.date) == (Decimal("5.60"), date(2026, 11, 12))


def test_service_keeps_the_last_good_rate_when_the_bcb_is_down() -> None:
    source, clock = FakeSource(), Clock()
    service = ExchangeRateService(source=source, clock=clock)
    service.snapshot()
    source.down = True
    clock.now += timedelta(hours=2)
    snapshot = service.snapshot()
    assert snapshot.rates["USD"].rate == Decimal("5.5606")
    assert snapshot.stale is True
    # Retries after a few minutes, not on every request.
    calls = len(source.calls)
    clock.now += timedelta(minutes=1)
    service.snapshot()
    assert len(source.calls) == calls
    source.down = False
    clock.now += timedelta(minutes=5)
    assert service.snapshot().stale is False


def test_service_without_any_rate_reports_unavailable_without_raising() -> None:
    source, clock = FakeSource(), Clock()
    source.down = True
    service = ExchangeRateService(source=source, clock=clock)
    snapshot = service.snapshot()
    assert (snapshot.rates, snapshot.stale, snapshot.fetched_at) == ({}, True, None)
    assert service.rate_for("USD") is None


def test_an_old_closing_after_a_long_outage_is_flagged() -> None:
    source, clock = FakeSource(), Clock()
    source.day = date(2026, 11, 2)
    snapshot = ExchangeRateService(source=source, clock=clock).snapshot()
    assert snapshot.rates["USD"].date == date(2026, 11, 2)
    assert snapshot.stale is True


def test_real_is_always_one() -> None:
    service = ExchangeRateService(source=FakeSource(), clock=Clock())
    assert service.rate_for("BRL").rate == Decimal("1")


def test_payload_is_strings_and_iso_dates() -> None:
    service = ExchangeRateService(source=FakeSource(), clock=Clock())
    assert snapshot_payload(service.snapshot()) == {
        "base": "BRL",
        "rates": {"EUR": {"rate": "6.1706", "date": "2026-11-11"}, "USD": {"rate": "5.5606", "date": "2026-11-11"}},
        "source": "PTAX/BCB",
        "stale": False,
        "fetchedAt": "2026-11-12T13:00:00Z",
    }


# --- Route -------------------------------------------------------------------------


async def authenticated_admin():
    yield ResolvedPrincipal(context=TEST_SESSION_CONTEXT, tenant_session=object())


def _client(tmp_path: Path, **options) -> TestClient:  # noqa: ANN003
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    app = create_app(
        database_instance=FakeDatabase(),
        static_dir=tmp_path,
        exchange_rate_service=ExchangeRateService(source=FakeSource(), clock=Clock()),
        **options,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_route_returns_the_current_rates_without_caching(tmp_path: Path) -> None:
    response = _client(tmp_path, principal_dependency=authenticated_admin).get("/api/exchange-rates")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["rates"]["USD"] == {"rate": "5.5606", "date": "2026-11-11"}


def test_route_requires_a_session(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/exchange-rates")
    assert response.status_code == 503
    assert "rates" not in response.json()
