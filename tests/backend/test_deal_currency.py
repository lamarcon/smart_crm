"""Deals in USD/EUR: currency rules, PTAX rate frozen on win, BRL summaries."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import DealPipelineStage
from app.repositories.company_deals import CompanyDealRepository
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.exchange_rates import ExchangeRate, ExchangeRateService, ExchangeRateUnavailable
from app.services.workspace import WorkspaceService
from tests.backend.test_workspace_service import TEST_PRINCIPAL, service, state_data  # noqa: F401


NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)  # 12:00 in Brasilia


class RateSource:
    """PTAX stand-in: the closing in force on a day is the one of that day."""

    def __init__(self) -> None:
        self.rates = {"USD": Decimal("5.5606"), "EUR": Decimal("6.1706")}
        self.down = False
        self.asked: list[tuple[str, date]] = []

    def latest_closing(self, currency: str, today: date) -> ExchangeRate:
        self.asked.append((currency, today))
        if self.down:
            raise ExchangeRateUnavailable("down")
        return ExchangeRate(currency, self.rates[currency], today)


def rates(source: RateSource, now: datetime = NOW) -> ExchangeRateService:
    return ExchangeRateService(source=source, clock=lambda: now)


def currency_state() -> dict:
    data = state_data()
    usd = deepcopy(data["deals"][0])
    usd.update(id="N-2", title="Em dólar", currency="USD", amount=100, quotes=[])
    eur = deepcopy(data["deals"][0])
    eur.update(id="N-3", title="Em euro", currency="eur", amount=200, quotes=[])
    data["deals"] += [usd, eur]
    return data


def won_stage_id(database) -> str:  # noqa: ANN001
    with database.session_scope() as session:
        return str(session.scalar(select(DealPipelineStage.id).where(
            DealPipelineStage.workspace_id == "default", DealPipelineStage.semantic_type == "won")))


def open_stage_id(database) -> str:  # noqa: ANN001
    with database.session_scope() as session:
        return str(session.scalar(select(DealPipelineStage.id).where(
            DealPipelineStage.workspace_id == "default", DealPipelineStage.semantic_type == "open")
            .order_by(DealPipelineStage.position)))


def save_as_admin(database, core: WorkspaceService, mutate):  # noqa: ANN001, ANN201
    with database.session_scope() as session:
        loaded = core.load(session, TEST_PRINCIPAL)
        data = loaded.state.model_dump(by_alias=True, exclude_none=True)
        mutate(data)
        return core.save(session, TEST_PRINCIPAL, loaded.version, WorkspaceState.model_validate(data))


def deal(result, deal_id: str) -> dict:  # noqa: ANN001
    return next(item for item in result.state.deals if item["id"] == deal_id)


def test_currency_is_normalized_and_brl_by_default(service) -> None:  # noqa: F811
    workspace, _database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    loaded = {item["id"]: item for item in workspace.load().state.deals}
    assert {key: loaded[key]["currency"] for key in loaded} == {"N-1": "BRL", "N-2": "USD", "N-3": "EUR"}


def test_unsupported_currency_is_refused(service) -> None:  # noqa: F811
    workspace, _database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    changed = workspace.load().state.model_dump(by_alias=True, exclude_none=True)
    changed["deals"][0]["currency"] = "GBP"
    with pytest.raises(WorkspaceReferenceError) as error:
        workspace.save(workspace.load().version, WorkspaceState.model_validate(changed))
    assert (error.value.path, error.value.message) == ("deals[0].currency", "Moeda não suportada. Use BRL, USD ou EUR.")


def test_winning_freezes_the_rate_of_the_win_day_and_the_client_cannot_change_it(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    source = RateSource()
    core = WorkspaceService(exchange_rates=rates(source), clock=lambda: NOW)
    won = won_stage_id(database)

    def win(data: dict) -> None:
        for item in data["deals"]:
            item["stageId"] = won
            item["fxRate"] = "1.0"  # forged by the client: ignored
    result = save_as_admin(database, core, win)
    assert {k: (deal(result, k).get("fxRate"), deal(result, k).get("fxRateDate")) for k in ("N-1", "N-2", "N-3")} == {
        "N-1": (None, None),
        "N-2": ("5.5606", "2026-11-12"),
        "N-3": ("6.1706", "2026-11-12"),
    }

    # Next day the dollar moves; the won deal keeps its frozen rate, forged values are ignored.
    source.rates["USD"] = Decimal("6.0")
    later = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    next_day = WorkspaceService(exchange_rates=rates(source, later), clock=lambda: later)

    def forge(data: dict) -> None:
        for item in data["deals"]:
            item["fxRate"], item["fxRateDate"] = "9.99", "2020-01-01"
    kept = save_as_admin(database, next_day, forge)
    assert (deal(kept, "N-2")["fxRate"], deal(kept, "N-2")["fxRateDate"]) == ("5.5606", "2026-11-12")


def test_reopening_clears_the_frozen_rate_and_switching_currency_refreezes(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    source = RateSource()
    core = WorkspaceService(exchange_rates=rates(source), clock=lambda: NOW)
    won, open_ = won_stage_id(database), open_stage_id(database)
    save_as_admin(database, core, lambda data: [item.update(stageId=won) for item in data["deals"]])

    switched = save_as_admin(database, core, lambda data: deal_update(data, "N-2", currency="EUR"))
    assert deal(switched, "N-2")["fxRate"] == "6.1706"

    reopened = save_as_admin(database, core, lambda data: deal_update(data, "N-2", stageId=open_))
    assert "fxRate" not in deal(reopened, "N-2") and "fxRateDate" not in deal(reopened, "N-2")


def deal_update(data: dict, deal_id: str, **fields) -> None:  # noqa: ANN003
    next(item for item in data["deals"] if item["id"] == deal_id).update(fields)


def test_a_win_without_rates_is_frozen_later_with_the_win_day_rate(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    source = RateSource()
    source.down = True
    won = won_stage_id(database)
    core = WorkspaceService(exchange_rates=rates(source), clock=lambda: NOW)
    unfrozen = save_as_admin(database, core, lambda data: deal_update(data, "N-2", stageId=won))
    assert "fxRate" not in deal(unfrozen, "N-2")

    # Next day the BCB is back: the rate in force on the win day is used.
    source.down = False
    later = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    next_day = WorkspaceService(exchange_rates=rates(source, later), clock=lambda: later)
    frozen = save_as_admin(database, next_day, lambda data: deal_update(data, "N-1", title="Outro ajuste"))
    assert (deal(frozen, "N-2")["fxRate"], deal(frozen, "N-2")["fxRateDate"]) == ("5.5606", "2026-11-12")
    assert ("USD", date(2026, 11, 12)) in source.asked


def test_company_summary_sums_in_brl_with_frozen_and_current_rates(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    source = RateSource()
    service_rates = rates(source)
    core = WorkspaceService(exchange_rates=service_rates, clock=lambda: NOW)
    won = won_stage_id(database)
    save_as_admin(database, core, lambda data: deal_update(data, "N-3", stageId=won))

    later = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    source.rates.update(USD=Decimal("6"), EUR=Decimal("7"))
    with database.session_scope() as session:
        summary = CompanyDealRepository(session, rates(source, later)).summary(TEST_PRINCIPAL, "E-1")
    payload = summary.model_dump(by_alias=True)
    # Open: R$ 10 + US$ 100 at today's 6.00. Won: € 200 frozen at 6.1706, not today's 7.
    assert payload["open"] == {"count": 2, "amount": "610.00"}
    assert payload["won"] == {"count": 1, "amount": "1234.12"}
    assert payload["ratesUnavailable"] is False
    rows = {row["id"]: (row["currency"], row["amount"], row["amountBrl"]) for row in payload["items"]}
    assert rows == {"N-1": ("BRL", "10.00", "10.00"), "N-2": ("USD", "100.00", "600.00"), "N-3": ("EUR", "200.00", "1234.12")}


def test_company_summary_without_rates_flags_the_unconverted_deals(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(currency_state()))
    source = RateSource()
    source.down = True
    with database.session_scope() as session:
        summary = CompanyDealRepository(session, rates(source)).summary(TEST_PRINCIPAL, "E-1")
    payload = summary.model_dump(by_alias=True)
    assert payload["open"] == {"count": 3, "amount": "10.00"}
    assert payload["ratesUnavailable"] is True
    assert {row["id"]: row["amountBrl"] for row in payload["items"]} == {"N-1": "10.00", "N-2": None, "N-3": None}
