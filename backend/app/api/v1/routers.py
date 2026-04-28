from fastapi import APIRouter

from app.api.v1.endpoints import dashboard, drones, fire_events, map_data, notification_recipients, streams, system


# v1 엔드포인트 라우터를 한곳에 모아 FastAPI 앱에 등록한다.
router = APIRouter()
router.include_router(system.router)
router.include_router(dashboard.router)
router.include_router(drones.router)
router.include_router(map_data.router)
router.include_router(notification_recipients.router)
router.include_router(fire_events.router)
router.include_router(streams.router)
