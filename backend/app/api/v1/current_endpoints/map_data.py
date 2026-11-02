from fastapi import APIRouter

from app.api.v1.endpoints.map_data import get_map_overview


router = APIRouter(tags=["current-map"])
router.get("/map/overview")(get_map_overview)
