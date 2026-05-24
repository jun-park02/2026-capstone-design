from fastapi import APIRouter

from app.api.v1.endpoints.dashboard import get_dashboard_summary


router = APIRouter(tags=["current-dashboard"])
router.get("/dashboard/summary")(get_dashboard_summary)
