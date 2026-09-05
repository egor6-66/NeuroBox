"""Точка входа приложения."""

from fastapi import FastAPI

from neurobox.api.main import api_router
from neurobox.core.config import settings

app = FastAPI(title=settings.project_name)

app.include_router(api_router)
