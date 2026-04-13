from fastapi import APIRouter

from app import runtime


router = APIRouter(tags=["system"])


@router.get("/")
def root():
    return {"msg": "root"}


@router.get("/health")
def health():
    """백엔드와 백그라운드 리스너의 현재 동작 상태를 반환한다."""
    return {
        "status": "healthy",
        "consumer_running": runtime.consumer.is_running if runtime.consumer else False,
        "consumer_name": runtime.consumer.consumer if runtime.consumer else None,
        "fire_listener_running": runtime.fire_listener.is_running if runtime.fire_listener else False,
        "last_fire_event_id": runtime.fire_listener.last_event_id if runtime.fire_listener else None,
    }
