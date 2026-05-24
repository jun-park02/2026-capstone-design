from fastapi import APIRouter

from app.api.v1.endpoints.fire_events import (
    get_fire_event_detail,
    list_fire_events,
    update_fire_event_status,
)


router = APIRouter(tags=["current-fire-events"])
router.get("/fire-events")(list_fire_events)
router.get("/fire-events/{event_id}")(get_fire_event_detail)
router.patch("/fire-events/{event_id}")(update_fire_event_status)
