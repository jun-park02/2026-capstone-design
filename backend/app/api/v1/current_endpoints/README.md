# Current Endpoints

This package contains the API subset currently called by the frontend.

The original `app.api.v1.endpoints` package is intentionally left unchanged.
These routers reuse the existing endpoint handler functions, so the current
contracts stay in one implementation while the frontend-facing subset is easy
to inspect or switch to later.

Currently grouped routes:

- `GET /dashboard/summary`
- `GET /map/overview`
- `GET /fire-events`
- `GET /fire-events/{event_id}`
- `PATCH /fire-events/{event_id}`
- `GET /notification-recipients`
- `POST /notification-recipients`
- `PATCH /notification-recipients/{email}`
- `DELETE /notification-recipients/{email}`

`current_endpoints.router` is not registered by default because registering it
alongside the existing routers would duplicate the same paths. To expose only
this subset later, import `router` from this package in `app.api.v1.routers`
instead of including the full endpoint modules.
