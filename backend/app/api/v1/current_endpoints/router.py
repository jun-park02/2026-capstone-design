from fastapi import APIRouter

from app.api.v1.current_endpoints import dashboard, fire_events, map_data, notification_recipients


router = APIRouter()
router.include_router(dashboard.router)
router.include_router(map_data.router)
router.include_router(fire_events.router)
router.include_router(notification_recipients.router)
