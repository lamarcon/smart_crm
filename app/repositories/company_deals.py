"""Canonical, authorization-scoped Company Deal summaries."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import Company, CrmUser, Deal, DealPipelineStage
from app.policies import PrincipalScope, RecordScope, can_read_record, deal_visibility_predicate
from app.schemas import CompanyDealMetricResponse, CompanyDealRow, CompanyDealSummaryResponse


ZERO = Decimal("0.00")


class CompanyDealRepository:
    """Read one Company's active visible Deals from canonical tenant tables."""

    def __init__(self, session: Session) -> None:
        self.session = session

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
        aggregate = self.session.execute(
            select(
                func.count(Deal.id).label("total_count"),
                *(
                    expression
                    for semantic in ("open", "won", "lost")
                    for expression in (
                        func.sum(
                            case((DealPipelineStage.semantic_type == semantic, 1), else_=0)
                        ).label(f"{semantic}_count"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (DealPipelineStage.semantic_type == semantic, Deal.amount),
                                    else_=ZERO,
                                )
                            ),
                            ZERO,
                        ).label(f"{semantic}_amount"),
                    )
                ),
            )
            .select_from(Deal)
            .join(DealPipelineStage, stage_join)
            .where(*visible)
        ).one()

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

        def metric(semantic: str) -> CompanyDealMetricResponse:
            return CompanyDealMetricResponse(
                count=int(getattr(aggregate, f"{semantic}_count") or 0),
                amount=Decimal(getattr(aggregate, f"{semantic}_amount") or ZERO),
            )

        return CompanyDealSummaryResponse(
            total_count=int(aggregate.total_count or 0),
            open=metric("open"),
            won=metric("won"),
            lost=metric("lost"),
            items=[
                CompanyDealRow(
                    id=row.id,
                    title=row.title,
                    stage_id=row.stage_id,
                    stage_name=row.stage_name,
                    semantic_type=row.semantic_type,
                    responsible_id=row.responsible_id,
                    responsible_name=row.responsible_name,
                    amount=Decimal(row.amount or ZERO),
                )
                for row in rows
            ],
        )
