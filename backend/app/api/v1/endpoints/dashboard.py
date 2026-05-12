from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import DashboardAggregate


router = APIRouter(tags=["dashboard"])


def _today_kst() -> date:
    return datetime.now(UTC).astimezone(timezone(timedelta(hours=9))).date()


def _serialize_aggregate(row: DashboardAggregate) -> dict:
    return {
        "id": row.id,
        "aggregate_date": row.aggregate_date.isoformat(),
        "metric_key": row.metric_key,
        "metric_value": float(row.metric_value),
        "metric_unit": row.metric_unit,
        "description": row.description,
        "extra": row.extra,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get(
    "/dashboard/aggregates",
    responses={
        200: {
            "description": "Dashboard aggregate metrics for a date.",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "aggregate_date": "2026-04-28",
                        "count": 3,
                        "items": [
                            {
                                "id": 1,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "total_fire_events",
                                "metric_value": 12.0,
                                "metric_unit": "count",
                                "description": "오늘 발생한 전체 화재 감지 이벤트 수",
                                "extra": None,
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                            {
                                "id": 2,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "fire_confirmed_events",
                                "metric_value": 4.0,
                                "metric_unit": "count",
                                "description": "오늘 확정된 실제 화재 이벤트 수",
                                "extra": None,
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                            {
                                "id": 3,
                                "aggregate_date": "2026-04-28",
                                "metric_key": "active_drone_count",
                                "metric_value": 2.0,
                                "metric_unit": "count",
                                "description": "최근 기준 활성 드론 수",
                                "extra": {"timeout_sec": 60},
                                "created_at": "2026-04-28T00:00:00",
                                "updated_at": "2026-04-28T00:05:00",
                            },
                        ],
                    }
                }
            },
        }
    },
)
def list_dashboard_aggregates(
    aggregate_date: date | None = Query(None),
    metric_key: list[str] | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블에서 지정한 날짜의 지표 목록을 조회한다.

    aggregate_date가 없으면 한국 시간 기준 오늘 날짜를 사용하고,
    metric_key가 전달되면 해당 지표들만 필터링한다.

    dashboard_aggregates 집계 테이블에서 데이터를 가져옴.
    현재는 테이블에 집계가 저장되지 않음.
    """
    target_date = aggregate_date or _today_kst()
    stmt = (
        select(DashboardAggregate)
        .where(DashboardAggregate.aggregate_date == target_date)
        .order_by(DashboardAggregate.metric_key)
    )
    if metric_key:
        stmt = stmt.where(DashboardAggregate.metric_key.in_(metric_key))

    rows = session.scalars(stmt).all()
    return {
        "ok": True,
        "aggregate_date": target_date.isoformat(),
        "count": len(rows),
        "items": [_serialize_aggregate(row) for row in rows],
    }


@router.get(
    "/dashboard/aggregates/ratio",
    responses={
        200: {
            "description": "Ratio between two dashboard aggregate metrics.",
            "content": {
                "application/json": {
                    "example": {
                        "ok": True,
                        "aggregate_date": "2026-04-28",
                        "numerator": {
                            "id": 2,
                            "aggregate_date": "2026-04-28",
                            "metric_key": "fire_confirmed_events",
                            "metric_value": 4.0,
                            "metric_unit": "count",
                            "description": "Confirmed fire events today.",
                            "extra": None,
                            "created_at": "2026-04-28T00:00:00",
                            "updated_at": "2026-04-28T00:05:00",
                        },
                        "denominator": {
                            "id": 1,
                            "aggregate_date": "2026-04-28",
                            "metric_key": "total_fire_events",
                            "metric_value": 12.0,
                            "metric_unit": "count",
                            "description": "Total fire detection events today.",
                            "extra": None,
                            "created_at": "2026-04-28T00:00:00",
                            "updated_at": "2026-04-28T00:05:00",
                        },
                        "ratio": 0.3333333333333333,
                        "percentage": 33.33333333333333,
                    }
                }
            },
        }
    },
)
def get_dashboard_aggregate_ratio(
    numerator_key: str = Query(..., min_length=1, max_length=100),
    denominator_key: str = Query(..., min_length=1, max_length=100),
    aggregate_date: date | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블의 두 지표를 이용해 비율을 계산한다.

    numerator_key / denominator_key 값을 반환하고,
    프론트에서 바로 표시할 수 있도록 percentage 값도 함께 내려준다.

    프론트에서 “확정 화재 비율”, “정상 처리 비율”, “성공률” 같은 걸 표시할 때 쓰는 엔드포인트
    """
    target_date = aggregate_date or _today_kst()
    rows = session.scalars(
        select(DashboardAggregate).where(
            DashboardAggregate.aggregate_date == target_date,
            DashboardAggregate.metric_key.in_([numerator_key, denominator_key]),
        )
    ).all()
    by_key = {row.metric_key: row for row in rows}
    numerator = by_key.get(numerator_key)
    denominator = by_key.get(denominator_key)
    if numerator is None or denominator is None:
        raise HTTPException(status_code=404, detail="aggregate metric not found")
    if denominator.metric_value == 0:
        raise HTTPException(status_code=400, detail="denominator metric is zero")

    ratio = Decimal(numerator.metric_value) / Decimal(denominator.metric_value)
    return {
        "ok": True,
        "aggregate_date": target_date.isoformat(),
        "numerator": _serialize_aggregate(numerator),
        "denominator": _serialize_aggregate(denominator),
        "ratio": float(ratio),
        "percentage": float(ratio * Decimal("100")),
    }


@router.get("/dashboard/aggregates/{metric_key}")
def get_dashboard_aggregate(
    metric_key: str,
    aggregate_date: date | None = Query(None),
    session: Session = Depends(get_db_session),
):
    """
    대시보드 집계 테이블에서 지정한 날짜의 단일 지표를 조회한다.

    aggregate_date가 없으면 한국 시간 기준 오늘 날짜를 사용한다.
    """
    target_date = aggregate_date or _today_kst()
    row = session.scalar(
        select(DashboardAggregate).where(
            DashboardAggregate.aggregate_date == target_date,
            DashboardAggregate.metric_key == metric_key,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="aggregate metric not found")

    return {"ok": True, "item": _serialize_aggregate(row)}
