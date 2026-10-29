from fastapi import APIRouter

from app.api.v1 import analytics, days, export, health, ingest, procurement

api_router = APIRouter(prefix="/api/v1")
for module in (health, ingest, analytics, procurement, days, export):
    api_router.include_router(module.router)
