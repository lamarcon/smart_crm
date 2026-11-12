"""Canonical, authorization-scoped Company Deal summaries."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Company, CrmUser, Deal, DealPipelineStage
from app.policies import PrincipalScope, RecordScope, can_read_record, deal_visibility_predicate
from app.schemas import CompanyDealMetricResponse, CompanyDealRow, CompanyDealSummaryResponse
from app.services.exchange_rates import BASE_CURRENCY, ExchangeRateService


ZERO = Decimal("0.00")


class CompanyDealRepository:
    """Read one Company's active visible Deals from canonical tenant tables."""

    def __init__(self, session: Session, exchange_rates: ExchangeRateService | None = None) -> None:
        self.session = session
        self.exchange_rates = exchange_rates

    def _amount_brl(self, amount: Decimal, currency: str, semantic: str, fx_rate: Decimal | None) -> Decimal | None:
        """BRL value: frozen rate for won deals, current PTAX rate otherwise."""

        if currency == BASE_CURRENCY:
            return amount
        if semantic == "won" and fx_rate is not None:
            return amount * fx_rate
        current = self.exchange_rates.rate_for(currency) if self.exchange_rates is not None else None
        return amount * current.rate if current is not None else None

    def summary(
        self,
        principal: PrincipalScope,
        company_id: str,
    ) -> CompanyDealSummaryResponse | None:
        company = self.session.scalar(
            select(Company).where(
                Company.workspace_id == principal.workspace_id,
                Company.id == company_id,
                Company.deleted_at.is_(None),
            )
        )
        if company is None or not can_read_record(
            principal,
            "companies",
            RecordScope(responsible_id=company.owner_id, assistant_ids=(), team_id=None),
        ):
            return None

        visible = (
            Deal.workspace_id == principal.workspace_id,
            Deal.company_id == company_id,
            Deal.deleted_at.is_(None),
            deal_visibility_predicate(principal),
        )
        stage_join = and_(
            DealPipelineStage.workspace_id == Deal.workspace_id,
            DealPipelineStage.pipeline_id == Deal.pipeline_id,
            DealPipelineStage.id == Deal.stage_id,
        )
        rows = self.session.execute(
            select(
                Deal.id,
                Deal.title,
                Deal.stage_id,
                DealPipelineStage.name.label("stage_name"),
                DealPipelineStage.semantic_type,
                Deal.responsible_id,
                CrmUser.name.label("responsible_name"),
                Deal.amount,
                Deal.currency,
                Deal.fx_rate,
            )
            .select_from(Deal)
            .join(DealPipelineStage, stage_join)
            .outerjoin(
                CrmUser,
                and_(
                    CrmUser.workspace_id == Deal.workspace_id,
                    CrmUser.id == Deal.responsible_id,
                ),
            )
            .where(*visible)
            .order_by(Deal.created_at.desc(), Deal.id.asc())
        ).all()

        items: list[CompanyDealRow] = []
        totals = {semantic: [0, ZERO] for semantic in ("open", "won", "lost")}
        unconverted = False
        for row in rows:
            amount = Decimal(row.amount or ZERO)
            currency = (row.currency or BASE_CURRENCY).upper()
            amount_brl = self._amount_brl(amount, currency, row.semantic_type, row.fx_rate)
            totals[row.semantic_type][0] += 1
            if amount_brl is None:
                unconverted = True
            else:
                totals[row.semantic_type][1] += amount_brl
            items.append(
                CompanyDealRow(
                    id=row.id,
                    title=row.title,
                    stage_id=row.stage_id,
                    stage_name=row.stage_name,
                    semantic_type=row.semantic_type,
                    responsible_id=row.responsible_id,
                    responsible_name=row.responsible_name,
                    amount=amount,
                    currency=currency,
                    amount_brl=amount_brl,
                )
            )

        def metric(semantic: str) -> CompanyDealMetricResponse:
            count, amount = totals[semantic]
            return CompanyDealMetricResponse(count=count, amount=amount)

        return CompanyDealSummaryResponse(
            total_count=len(items),
            open=metric("open"),
            won=metric("won"),
            lost=metric("lost"),
            items=items,
            rates_unavailable=unconverted,
        )
