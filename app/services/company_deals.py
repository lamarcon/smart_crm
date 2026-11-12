"""Authorized Company Deal summary orchestration."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.policies import PrincipalScope
from app.repositories.company_deals import CompanyDealRepository
from app.schemas import CompanyDealSummaryResponse
from app.services.exchange_rates import ExchangeRateService


class CompanyDealNotFoundError(Exception):
    """The requested Company is missing or outside the principal's scope."""


class CompanyDealService:
    """Expose the canonical Company Deal read model without leaking existence."""

    def __init__(self, exchange_rates: ExchangeRateService | None = None) -> None:
        self.exchange_rates = exchange_rates

    def summary(
        self,
        session: Session,
        principal: PrincipalScope,
        company_id: str,
    ) -> CompanyDealSummaryResponse:
        result = CompanyDealRepository(session, self.exchange_rates).summary(principal, company_id)
        if result is None:
            raise CompanyDealNotFoundError("company not found")
        return result
