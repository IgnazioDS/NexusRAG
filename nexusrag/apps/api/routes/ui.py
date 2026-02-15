from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, idempotency_key_header, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AuditEvent,
    Document,
    Plan,
    UiAction,
    UsageCounter,
    PlanLimit,
)
from nexusrag.ingestion.chunking import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.authz.abac import authorize_document_action, filter_documents_for_principal
from nexusrag.services.entitlements import (
    FEATURE_AUDIT,
    FEATURE_BILLING_WEBHOOK_TEST,
    FEATURE_OPS_ADMIN,
    FEATURE_TTS,
    FeatureEntitlement,
    DEFAULT_PLAN_ID,
    get_active_plan_assignment,
    get_effective_entitlements,
    require_feature,
)
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.ingest.queue import IngestionJobPayload, enqueue_ingestion_job
from nexusrag.services.ui_dashboard import build_dashboard_alerts, build_dashboard_cards
from nexusrag.services.ui_query import (
    CursorError,
    SortField,
    SortSpec,
    build_cursor_filter,
    build_cursor_payload,
    decode_cursor,
    encode_cursor,
    parse_sort,
    sort_token,
    validate_cursor_payload,
)
from nexusrag.services.usage_dashboard import aggregate_request_counts, build_timeseries_points


router = APIRouter(tags=["ui"], responses=DEFAULT_ERROR_RESPONSES)


class UiPrincipal(BaseModel):
    tenant_id: str
    role: str
    api_key_id: str
    subject_id: str


class UiPlan(BaseModel):
    plan_id: str
    plan_name: str | None


class UiEntitlement(BaseModel):
    enabled: bool
    config_json: dict[str, Any] | None = None


class UiQuotaSnapshot(BaseModel):
    day: dict[str, Any]
    month: dict[str, Any]
    soft_cap_reached: bool
    hard_cap_mode: str


class UiBootstrapData(BaseModel):
    principal: UiPrincipal
    plan: UiPlan
    entitlements: dict[str, UiEntitlement]
    quota_snapshot: UiQuotaSnapshot
    feature_flags: dict[str, bool]
    server_time: str
    api: dict[str, str]


class UiCard(BaseModel):
    id: str
    title: str
    value: str
    subtitle: str | None = None


class UiChart(BaseModel):
    id: str
    points: list[dict[str, Any]]


class UiAlert(BaseModel):
    id: str
    message: str
    severity: str


class UiDashboardData(BaseModel):
    cards: list[UiCard]
    charts: dict[str, UiChart]
    alerts: list[UiAlert]


class UiPage(BaseModel):
    next_cursor: str | None
    has_more: bool


class UiFacetValue(BaseModel):
    value: str
    count: int


class UiDocumentRow(BaseModel):
    id: str
    filename: str
    status: str
    corpus_id: str
    content_type: str
    created_at: str
    updated_at: str
    last_reindexed_at: str | None


class UiDocumentsData(BaseModel):
    items: list[UiDocumentRow]
    page: UiPage
    facets: dict[str, list[UiFacetValue]]


class UiActivityItem(BaseModel):
    id: int
    occurred_at: str
    event_type: str
    outcome: str
    actor_type: str | None
    actor_id: str | None
    resource_type: str | None
    resource_id: str | None
    summary: str


class UiActivityData(BaseModel):
    items: list[UiActivityItem]
    page: UiPage
    facets: dict[str, list[UiFacetValue]]


class UiActionOptimisticPatch(BaseModel):
    entity: str
    id: str
    patch: dict[str, Any]


class UiActionResponse(BaseModel):
    action_id: str
    status: str
    accepted_at: str
    optimistic: UiActionOptimisticPatch
    poll_url: str


class UiReindexRequest(BaseModel):
    document_id: str
    idempotency_key: str | None = Field(default=None, max_length=128)


def _utc_now() -> datetime:
    # Use UTC to keep UI timestamps aligned with server-side quotas.
    return datetime.now(timezone.utc)


def _quota_snapshot(limit: int | None, used: int) -> dict[str, Any]:
    # Render quota snapshots with remaining counts while preserving unlimited semantics.
    remaining = None if limit is None else max(limit - used, 0)
    return {"limit": limit, "used": used, "remaining": remaining}


async def _get_quota_state(db: AsyncSession, tenant_id: str) -> UiQuotaSnapshot:
    # Load quota state without mutating usage counters.
    now = _utc_now()
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
    plan_limit = result.scalar_one_or_none()

    soft_cap_ratio = plan_limit.soft_cap_ratio if plan_limit else 0.8
    hard_cap_mode = "enforce" if (plan_limit.hard_cap_enabled if plan_limit else True) else "observe"

    result = await db.execute(
        select(UsageCounter).where(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_type == "day",
            UsageCounter.period_start == day_start,
        )
    )
    day_counter = result.scalar_one_or_none()
    day_used = int(day_counter.requests_count) if day_counter else 0

    result = await db.execute(
        select(UsageCounter).where(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_type == "month",
            UsageCounter.period_start == month_start,
        )
    )
    month_counter = result.scalar_one_or_none()
    month_used = int(month_counter.requests_count) if month_counter else 0

    day_limit = plan_limit.daily_requests_limit if plan_limit else None
    month_limit = plan_limit.monthly_requests_limit if plan_limit else None

    day_snapshot = _quota_snapshot(day_limit, day_used)
    month_snapshot = _quota_snapshot(month_limit, month_used)

    soft_cap_reached = False
    if day_limit:
        soft_cap_reached = soft_cap_reached or day_used >= day_limit * soft_cap_ratio
    if month_limit:
        soft_cap_reached = soft_cap_reached or month_used >= month_limit * soft_cap_ratio

    return UiQuotaSnapshot(
        day=day_snapshot,
        month=month_snapshot,
        soft_cap_reached=soft_cap_reached,
        hard_cap_mode=hard_cap_mode,
    )


def _invalid_cursor_error() -> HTTPException:
    # Standardize invalid cursor errors for UI pagination.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "INVALID_CURSOR", "message": "Invalid cursor"},
    )


async def _enqueue_or_fail(
    *,
    db: AsyncSession,
    document_id: str,
    payload: IngestionJobPayload,
) -> None:
    # Update document status if ingestion queue is unavailable.
    try:
        await enqueue_ingestion_job(payload)
    except Exception as exc:  # noqa: BLE001 - surface queue failures as 503s
        await documents_repo.update_status(
            db,
            document_id,
            status="failed",
            error_message="Ingestion queue unavailable",
            failure_reason="Ingestion queue unavailable",
            completed_at=_utc_now(),
            last_job_id=payload.request_id,
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "QUEUE_ERROR", "message": "Ingestion queue unavailable"},
        ) from exc


@router.get("/ui/bootstrap", response_model=SuccessEnvelope[UiBootstrapData])
async def ui_bootstrap(
    request: Request,
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Aggregate tenant bootstrapping data for UI initialization.
    assignment = await get_active_plan_assignment(db, principal.tenant_id)
    plan_id = assignment.plan_id if assignment else DEFAULT_PLAN_ID
    try:
        plan_row = await db.execute(select(Plan).where(Plan.id == plan_id))
        plan = plan_row.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching plan") from exc

    entitlements = await get_effective_entitlements(db, principal.tenant_id)
    entitlements_payload = {
        key: UiEntitlement(
            enabled=value.enabled,
            config_json=value.config,
        )
        for key, value in entitlements.items()
    }
    quota_state = await _get_quota_state(db, principal.tenant_id)

    feature_flags = {
        "tts_enabled": entitlements.get(FEATURE_TTS, FeatureEntitlement(False)).enabled,
        "ops_admin_access": entitlements.get(FEATURE_OPS_ADMIN, FeatureEntitlement(False)).enabled,
        "audit_access": entitlements.get(FEATURE_AUDIT, FeatureEntitlement(False)).enabled,
        "billing_webhook_test": entitlements.get(
            FEATURE_BILLING_WEBHOOK_TEST, FeatureEntitlement(False)
        ).enabled,
    }

    payload = UiBootstrapData(
        principal=UiPrincipal(
            tenant_id=principal.tenant_id,
            role=principal.role,
            api_key_id=principal.api_key_id,
            subject_id=principal.subject_id,
        ),
        plan=UiPlan(plan_id=plan_id, plan_name=plan.name if plan else None),
        entitlements=entitlements_payload,
        quota_snapshot=quota_state,
        feature_flags=feature_flags,
        server_time=_utc_now().isoformat(),
        api={"version": "v1"},
    )
    return success_response(request=request, data=payload)


@router.get("/ui/dashboard/summary", response_model=SuccessEnvelope[UiDashboardData])
async def ui_dashboard_summary(
    request: Request,
    window_days: int = Query(default=30, ge=1, le=90),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Provide dashboard cards, charts, and alerts for the UI.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_AUDIT)
    window_start = _utc_now() - timedelta(days=window_days)

    try:
        result = await db.execute(
            select(AuditEvent.metadata_json)
            .where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "auth.access.success",
                AuditEvent.occurred_at >= window_start,
            )
            .order_by(AuditEvent.occurred_at.desc())
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while aggregating usage") from exc

    metadata_rows = [row[0] for row in result.all()]
    counts = aggregate_request_counts(metadata_rows)

    try:
        rate_limit_row = await db.execute(
            select(func.count(AuditEvent.id), func.max(AuditEvent.occurred_at)).where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "security.rate_limited",
                AuditEvent.occurred_at >= window_start,
            )
        )
        rate_limit_count, rate_limit_last = rate_limit_row.one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching rate limit hits") from exc

    try:
        status_rows = await db.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.tenant_id == principal.tenant_id)
            .group_by(Document.status)
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while aggregating ingestion") from exc

    ingestion_counts = {"queued": 0, "processing": 0, "succeeded": 0, "failed": 0}
    for status_value, count in status_rows.all():
        if status_value in ingestion_counts:
            ingestion_counts[status_value] = int(count or 0)

    quota_state = await _get_quota_state(db, principal.tenant_id)

    try:
        highlight_rows = await db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.occurred_at >= window_start,
            )
            .order_by(AuditEvent.occurred_at.desc())
            .limit(5)
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching audit highlights") from exc

    cards = [
        UiCard(**card)
        for card in build_dashboard_cards(
            request_total=counts.total,
            day_quota_used=int(quota_state.day["used"]),
            month_quota_used=int(quota_state.month["used"]),
            rate_limit_count=int(rate_limit_count or 0),
        )
    ]

    points_by_date: dict[datetime.date, int] = {}
    try:
        rows = await db.execute(
            select(func.date_trunc("day", AuditEvent.occurred_at), func.count(AuditEvent.id))
            .where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "auth.access.success",
                AuditEvent.occurred_at >= window_start,
            )
            .group_by(func.date_trunc("day", AuditEvent.occurred_at))
            .order_by(func.date_trunc("day", AuditEvent.occurred_at))
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while building usage series") from exc
    for bucket, count in rows.all():
        points_by_date[bucket.date()] = int(count or 0)
    chart_points = build_timeseries_points(
        start_date=window_start.date(),
        days=window_days,
        counts_by_date=points_by_date,
    )

    highlight_messages = [
        f"{event.event_type} ({event.outcome})" for event in highlight_rows.scalars().all()
    ]
    alerts = [
        UiAlert(**alert)
        for alert in build_dashboard_alerts(
            soft_cap_reached=quota_state.soft_cap_reached,
            rate_limit_count=int(rate_limit_count or 0),
            highlight_messages=highlight_messages,
        )
    ]

    payload = UiDashboardData(
        cards=cards,
        charts={"requests": UiChart(id="requests", points=chart_points)},
        alerts=alerts,
    )
    return success_response(request=request, data=payload)


@router.get("/ui/documents", response_model=SuccessEnvelope[UiDocumentsData])
async def ui_documents(
    request: Request,
    q: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
    status: str | None = None,
    corpus_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Provide a cursor-based document listing tailored for UI tables.
    sort_specs = {
        "created_at": SortSpec(Document.created_at),
        "updated_at": SortSpec(Document.updated_at),
        "filename": SortSpec(Document.filename),
        "status": SortSpec(Document.status),
    }
    default_sort = [SortField("created_at", sort_specs["created_at"], "desc")]
    try:
        sort_fields = parse_sort(sort=sort, allowed=sort_specs, default=default_sort)
    except CursorError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc

    settings = get_settings()
    sort_signature = sort_token(sort_fields)
    cursor_payload: dict[str, Any] | None = None
    if cursor:
        try:
            decoded = decode_cursor(cursor, settings.ui_cursor_secret)
            cursor_payload = validate_cursor_payload(
                payload=decoded,
                expected_scope="ui.documents",
                expected_tenant_id=principal.tenant_id,
                expected_sort=sort_signature,
            )
        except CursorError as exc:
            raise _invalid_cursor_error() from exc

    stmt = select(Document).where(Document.tenant_id == principal.tenant_id)
    if corpus_id:
        stmt = stmt.where(Document.corpus_id == corpus_id)
    if status:
        stmt = stmt.where(Document.status == status)
    if created_from:
        stmt = stmt.where(Document.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Document.created_at <= created_to)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.filename.ilike(like), Document.id.ilike(like)))

    if cursor_payload is not None:
        try:
            stmt = stmt.where(
                build_cursor_filter(
                    sort_fields=sort_fields,
                    cursor_values=cursor_payload["values"],
                    row_id=str(cursor_payload["id"]),
                    id_column=Document.id,
                )
            )
        except CursorError as exc:
            raise _invalid_cursor_error() from exc

    order_by = [
        field.spec.column.desc() if field.direction == "desc" else field.spec.column.asc()
        for field in sort_fields
    ]
    id_direction = sort_fields[0].direction
    order_by.append(Document.id.desc() if id_direction == "desc" else Document.id.asc())

    # Fetch extra rows to preserve cursor pagination after authorization filtering.
    authorized_rows: list[Document] = []
    next_cursor_payload = cursor_payload
    while len(authorized_rows) < limit + 1:
        page_stmt = stmt
        if next_cursor_payload is not None:
            try:
                page_stmt = page_stmt.where(
                    build_cursor_filter(
                        sort_fields=sort_fields,
                        cursor_values=next_cursor_payload["values"],
                        row_id=str(next_cursor_payload["id"]),
                        id_column=Document.id,
                    )
                )
            except CursorError as exc:
                raise _invalid_cursor_error() from exc
        try:
            result = await db.execute(page_stmt.order_by(*order_by).limit(limit + 1))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=500, detail="Database error while listing documents") from exc

        rows = list(result.scalars().all())
        if not rows:
            break
        filtered = await filter_documents_for_principal(
            session=db,
            principal=principal,
            documents=rows,
            action="read",
            request=request,
        )
        authorized_rows.extend(filtered)
        if len(rows) <= limit:
            break
        last_doc = rows[-1]
        next_cursor_payload = build_cursor_payload(
            scope="ui.documents",
            tenant_id=principal.tenant_id,
            sort_fields=sort_fields,
            row_values={field.name: getattr(last_doc, field.name) for field in sort_fields},
            row_id=last_doc.id,
        )

    has_more = len(authorized_rows) > limit
    rows = authorized_rows[:limit]

    items = [
        UiDocumentRow(
            id=doc.id,
            filename=doc.filename,
            status=doc.status,
            corpus_id=doc.corpus_id,
            content_type=doc.content_type,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat(),
            last_reindexed_at=doc.last_reindexed_at.isoformat() if doc.last_reindexed_at else None,
        )
        for doc in rows
    ]

    next_cursor = None
    if has_more and rows:
        last_doc = rows[-1]
        cursor_payload = build_cursor_payload(
            scope="ui.documents",
            tenant_id=principal.tenant_id,
            sort_fields=sort_fields,
            row_values={field.name: getattr(last_doc, field.name) for field in sort_fields},
            row_id=last_doc.id,
        )
        next_cursor = encode_cursor(cursor_payload, settings.ui_cursor_secret)

    # Build status facets from authorized results to avoid leaking counts.
    status_counts: dict[str, int] = {}
    for doc in rows:
        status_counts[doc.status] = status_counts.get(doc.status, 0) + 1
    facets = {
        "status": [
            UiFacetValue(value=status_value, count=count)
            for status_value, count in status_counts.items()
        ]
    }

    payload = UiDocumentsData(
        items=items,
        page=UiPage(next_cursor=next_cursor, has_more=has_more),
        facets=facets,
    )
    return success_response(request=request, data=payload)


@router.get("/ui/activity", response_model=SuccessEnvelope[UiActivityData])
async def ui_activity(
    request: Request,
    q: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
    actor_type: str | None = None,
    event_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Provide a normalized activity feed for UI timelines.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_AUDIT)
    sort_specs = {
        "occurred_at": SortSpec(AuditEvent.occurred_at),
        "event_type": SortSpec(AuditEvent.event_type),
        "outcome": SortSpec(AuditEvent.outcome),
    }
    default_sort = [SortField("occurred_at", sort_specs["occurred_at"], "desc")]
    try:
        sort_fields = parse_sort(sort=sort, allowed=sort_specs, default=default_sort)
    except CursorError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc

    settings = get_settings()
    sort_signature = sort_token(sort_fields)
    cursor_payload: dict[str, Any] | None = None
    if cursor:
        try:
            decoded = decode_cursor(cursor, settings.ui_cursor_secret)
            cursor_payload = validate_cursor_payload(
                payload=decoded,
                expected_scope="ui.activity",
                expected_tenant_id=principal.tenant_id,
                expected_sort=sort_signature,
            )
        except CursorError as exc:
            raise _invalid_cursor_error() from exc

    stmt = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id)
    if actor_type:
        stmt = stmt.where(AuditEvent.actor_type == actor_type)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if created_from:
        stmt = stmt.where(AuditEvent.occurred_at >= created_from)
    if created_to:
        stmt = stmt.where(AuditEvent.occurred_at <= created_to)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                AuditEvent.event_type.ilike(like),
                AuditEvent.resource_id.ilike(like),
                AuditEvent.actor_id.ilike(like),
            )
        )

    if cursor_payload is not None:
        try:
            stmt = stmt.where(
                build_cursor_filter(
                    sort_fields=sort_fields,
                    cursor_values=cursor_payload["values"],
                    row_id=cursor_payload["id"],
                    id_column=AuditEvent.id,
                )
            )
        except CursorError as exc:
            raise _invalid_cursor_error() from exc

    order_by = [
        field.spec.column.desc() if field.direction == "desc" else field.spec.column.asc()
        for field in sort_fields
    ]
    id_direction = sort_fields[0].direction
    order_by.append(AuditEvent.id.desc() if id_direction == "desc" else AuditEvent.id.asc())

    try:
        result = await db.execute(stmt.order_by(*order_by).limit(limit + 1))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while listing activity") from exc

    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        UiActivityItem(
            id=event.id,
            occurred_at=event.occurred_at.isoformat(),
            event_type=event.event_type,
            outcome=event.outcome,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            summary=f"{event.event_type} ({event.outcome})",
        )
        for event in rows
    ]

    next_cursor = None
    if has_more and rows:
        last_event = rows[-1]
        cursor_payload = build_cursor_payload(
            scope="ui.activity",
            tenant_id=principal.tenant_id,
            sort_fields=sort_fields,
            row_values={field.name: getattr(last_event, field.name) for field in sort_fields},
            row_id=last_event.id,
        )
        next_cursor = encode_cursor(cursor_payload, settings.ui_cursor_secret)

    facet_stmt = select(AuditEvent.event_type, func.count(AuditEvent.id)).where(
        AuditEvent.tenant_id == principal.tenant_id
    )
    if actor_type:
        facet_stmt = facet_stmt.where(AuditEvent.actor_type == actor_type)
    if created_from:
        facet_stmt = facet_stmt.where(AuditEvent.occurred_at >= created_from)
    if created_to:
        facet_stmt = facet_stmt.where(AuditEvent.occurred_at <= created_to)
    if q:
        like = f"%{q}%"
        facet_stmt = facet_stmt.where(
            or_(
                AuditEvent.event_type.ilike(like),
                AuditEvent.resource_id.ilike(like),
                AuditEvent.actor_id.ilike(like),
            )
        )
    facet_stmt = facet_stmt.group_by(AuditEvent.event_type)
    try:
        facet_rows = await db.execute(facet_stmt)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while aggregating facets") from exc

    facets = {
        "event_type": [
            UiFacetValue(value=event_value, count=int(count or 0))
            for event_value, count in facet_rows.all()
        ]
    }

    payload = UiActivityData(
        items=items,
        page=UiPage(next_cursor=next_cursor, has_more=has_more),
        facets=facets,
    )
    return success_response(request=request, data=payload)


@router.post(
    "/ui/actions/reindex-document",
    status_code=202,
    response_model=SuccessEnvelope[UiActionResponse],
)
async def ui_reindex_document(
    request: Request,
    payload: UiReindexRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Trigger a document reindex while returning optimistic UI state.
    tenant_id = principal.tenant_id
    try:
        doc = await documents_repo.get_document(db, tenant_id, payload.document_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching document") from exc
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    # Enforce ABAC + ACL before reindexing document content.
    await authorize_document_action(
        session=db,
        principal=principal,
        document=doc,
        action="reindex",
        request=request,
    )
    if doc.status in {"queued", "processing"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACTION_CONFLICT",
                "message": "Document ingestion is already in progress",
            },
        )
    if not doc.storage_path:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INGEST_SOURCE_MISSING",
                "message": "Document source text is not available for reindexing",
            },
        )

    request_hash = compute_request_hash({"document_id": payload.document_id})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
        key_override=payload.idempotency_key,
    )
    if replay is not None:
        return build_replay_response(replay)

    request_id = str(uuid4())
    queued_at = _utc_now()

    try:
        # Reset status fields and enqueue the reindex job for async processing.
        doc.status = "queued"
        doc.error_message = None
        doc.failure_reason = None
        doc.queued_at = queued_at
        doc.processing_started_at = None
        doc.completed_at = None
        doc.last_job_id = request_id
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating document") from exc

    ingest_payload = IngestionJobPayload(
        tenant_id=tenant_id,
        corpus_id=doc.corpus_id,
        document_id=payload.document_id,
        ingest_source=doc.ingest_source,
        storage_path=doc.storage_path,
        raw_text=None,
        filename=doc.filename,
        metadata_json=doc.metadata_json,
        chunk_size_chars=CHUNK_SIZE_CHARS,
        chunk_overlap_chars=CHUNK_OVERLAP_CHARS,
        request_id=request_id,
        is_reindex=True,
    )
    await _enqueue_or_fail(db=db, document_id=payload.document_id, payload=ingest_payload)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="documents.reindex.enqueued",
        outcome="success",
        resource_type="document",
        resource_id=payload.document_id,
        request_id=request_id,
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "corpus_id": doc.corpus_id,
            "chunk_size_chars": CHUNK_SIZE_CHARS,
            "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
        },
        commit=True,
        best_effort=True,
    )

    action_id = uuid4().hex
    ui_action = UiAction(
        id=action_id,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        action_type="documents.reindex",
        request_json={"document_id": payload.document_id},
        status="accepted",
        result_json={"document_id": payload.document_id, "job_id": request_id},
    )
    db.add(ui_action)
    try:
        await db.commit()
        await db.refresh(ui_action)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while recording action") from exc

    accepted_at = ui_action.created_at or _utc_now()
    response_payload = UiActionResponse(
        action_id=action_id,
        status="accepted",
        accepted_at=accepted_at.isoformat(),
        optimistic=UiActionOptimisticPatch(
            entity="document",
            id=payload.document_id,
            patch={"status": "queued"},
        ),
        poll_url=f"/v1/documents/{payload.document_id}",
    )
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=202,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body
