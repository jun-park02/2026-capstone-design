import time as time_module
from datetime import UTC, date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app import app_state
from app.db import get_db_session
from app.models import DashboardAggregate, DroneTelemetry, FireEvent, FireEventEmailNotification
from app.api.v1.endpoints.utils.dashboard import (
    _active_drone_count,
    _average_battery_percent,
    _average_delay_seconds,
    _count_fire_events_between,
    _count_pending_suspected_events,
    _dashboard_drone_paths,
    _dashboard_status,
    _day_bounds_utc,
    _drone_warning_error_count,
    _monthly_fire_data,
    _recent_fire_positions,
    _serialize_aggregate,
    _today_kst,
    _weekly_fire_data,
)

router = APIRouter(tags=["dashboard"])

@router.get("/dashboard/summary")
def get_dashboard_summary(
    session: Session = Depends(get_db_session),
):
    """
    대시보드 화면이 필요로 하는 전체 응답 데이터를 한 번에 반환
    화재 이벤트 집계, 드론 상태, 최신 배터리 데이터, 지도 표시용 좌표를 함께 리턴
    """
    # 한국 시간(KST, UTC+9) 기준 집계 범위와 최근 30일 통계 기준 시점을 계산한다.
    # today_start, today_end, target_date = _day_bounds_utc()
    today_start, today_end = _day_bounds_utc()
    evaluated_at = datetime.utcnow()
    recent_month_start = evaluated_at - timedelta(days=30)

    # 메일 발송 후 아직 확인되지 않은 의심 이벤트 수
    active_suspects = _count_pending_suspected_events(session)
    # 오늘 처리된 이벤트 수를 계산
    resolved_today = _count_fire_events_between(
        session=session,
        start_at=today_start,
        end_at=today_end,
        reviewed_only=True,
    )
    # 오늘 사용자 확인 결과가 실제 화재(Y)로 확정된 이벤트 수
    active_fires = _count_fire_events_between(
        session=session,
        start_at=today_start,
        end_at=today_end,
        confirmation="Y",
    )

    # 최근 30일 기준 전체 탐지, 실제 화재, 오탐지 건수를 계산한다.
    month_total = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
    )
    month_real = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
        confirmation="Y",
    )
    month_false_positive = _count_fire_events_between(
        session=session,
        start_at=recent_month_start,
        end_at=evaluated_at,
        confirmation="N",
    )

    # Redis 캐시나 DB에서 드론 경로를 가져오고, 첫 번째 드론을 대표 위치로 사용한다.
    drone_paths = _dashboard_drone_paths(session)
    primary_path = drone_paths[0]["path"] if drone_paths else []
    primary_latest = drone_paths[0]["latest"] if drone_paths else None
    if primary_latest:
        drone_lat = primary_latest["lat"]
        drone_lon = primary_latest["lon"]
        drone_alt = primary_latest.get("alt") or 0
    else:
        # 아직 드론 좌표가 없으면 기본 지도 중심 좌표로 대체한다.
        drone_lat = None
        drone_lon = None
        drone_alt = None

    # 오늘 발생한 실제 화재 위치 목록만 지도 마커로 사용한다.
    fire_locations = _recent_fire_positions(
        session,
        start_at=today_start,
        end_at=today_end,
    )

    # 프론트 대시보드 컴포넌트가 바로 사용할 수 있는 형태로 지표와 지도 데이터를 묶어 반환한다.
    return {
        "ok": True,
        # "date": target_date,
        "evaluated_at": evaluated_at.isoformat() + "Z",
        "status": _dashboard_status(session),
        "activeSuspects": active_suspects,
        "resolvedToday": resolved_today,
        "activeFires": active_fires,
        "avgDelay": _average_delay_seconds(session, start_at=today_start, end_at=today_end),
        "activeDrones": _active_drone_count(),
        "errorCount": _drone_warning_error_count(session, start_at=today_start, end_at=today_end),
        "avgBattery": _average_battery_percent(session),
        "droneLocation": {
            "lat": drone_lat,
            "lng": drone_lon,
            "alt": drone_alt,
        },
        "yearlyData": _monthly_fire_data(session),
        "weeklyData": _weekly_fire_data(session),
        "pieData": [
            {"name": "실제 화재", "value": month_real},
            {"name": "오탐지", "value": month_false_positive},
        ],
        "dronePath": [point["position"] for point in primary_path],
        "fireLocations": fire_locations,
        "monthTotal": month_total,
        "monthReal": month_real,
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
