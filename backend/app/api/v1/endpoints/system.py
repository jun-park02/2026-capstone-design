from fastapi import APIRouter

from app import runtime


router = APIRouter(tags=["system"])


@router.get("/")
def root():
    return {"msg": "root"}


@router.get(
    "/health",
    responses={
        200: {
            "description": "Backend background resource health status.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "consumer_running": True,
                        "consumer_name": "consumer-1",
                        "fire_listener_running": True,
                        "last_fire_event_id": "1714287600000-0",
                    }
                }
            },
        }
    },
)
def health():
    """백엔드와 백그라운드 리스너의 현재 동작 상태를 반환한다."""
    return {
        "status": "healthy",
        "consumer_running": runtime.consumer.is_running if runtime.consumer else False,
        "consumer_name": runtime.consumer.consumer if runtime.consumer else None,
        "fire_listener_running": runtime.fire_listener.is_running if runtime.fire_listener else False,
        "last_fire_event_id": runtime.fire_listener.last_event_id if runtime.fire_listener else None,
    }
