"""Authorized Company Deal summary orchestration."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.policies import PrincipalScope
from app.repositories.company_deals import CompanyDealRepository
from app.schemas import CompanyDealSummaryResponse


class CompanyDealNotFoundError(Exception):
    """The requested Company is missing or outside the principal's scope."""


class CompanyDealService:
    """Expose the canonical Company Deal read model without leaking existence."""

    def summary(
        self,
        session: Session,
        principal: PrincipalScope,
        company_id: str,
    ) -> CompanyDealSummaryResponse:
        result = CompanyDealRepository(session).summary(principal, company_id)
        if result is None:
            raise CompanyDealNotFoundError("company not found")
        return result
