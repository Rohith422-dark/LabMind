from app.routers import (
    audit, auth, chat, dashboard, demo, documents, gaps, health, inventory, notifications, requests, troubleshoot, users,
)

ROUTERS = [
    health.router, auth.router, users.router, audit.router, documents.router, chat.router, gaps.router,
    troubleshoot.router, inventory.router, requests.router, notifications.router, dashboard.router, demo.router,
]
