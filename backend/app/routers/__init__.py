from app.routers import (
    audit, auth, chat, dashboard, demo, documents, experiments, gaps, health, inventory, notifications, project_chat,
    project_documents, projects, requests, troubleshoot, users,
)

ROUTERS = [
    health.router, auth.router, users.router, audit.router, documents.router, chat.router, gaps.router,
    troubleshoot.router, inventory.router, requests.router, notifications.router, dashboard.router, demo.router,
    projects.router, experiments.router, project_documents.router, project_chat.router, project_chat.user_router,
]
