from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db_session
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
