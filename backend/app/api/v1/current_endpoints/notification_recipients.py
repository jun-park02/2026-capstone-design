from fastapi import APIRouter

from app.api.v1.endpoints.notification_recipients import (
    delete_notification_recipient,
    list_notification_recipients,
    register_notification_recipients,
    update_notification_recipient,
)


router = APIRouter(tags=["current-notification-recipients"])
router.get("/notification-recipients")(list_notification_recipients)
router.post("/notification-recipients")(register_notification_recipients)
router.patch("/notification-recipients/{email}")(update_notification_recipient)
router.delete("/notification-recipients/{email}", status_code=204)(delete_notification_recipient)
