from fastapi import APIRouter

from app import app_state


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
        "consumer_running": app_state.consumer.is_running if app_state.consumer else False,
        "consumer_name": app_state.consumer.consumer if app_state.consumer else None,
        "fire_listener_running": app_state.fire_listener.is_running if app_state.fire_listener else False,
        "last_fire_event_id": app_state.fire_listener.last_event_id if app_state.fire_listener else None,
    }
