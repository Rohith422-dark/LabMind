from app.routers import audit, auth, health, users

ROUTERS = [health.router, auth.router, users.router, audit.router]
