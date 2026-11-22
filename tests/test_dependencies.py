from unittest.mock import MagicMock

from fastapi import FastAPI

import app.dependencies as dependencies
from app.config import Settings
from app.main import create_app


def test_build_dependencies_wires_create_app(monkeypatch):
    settings = Settings(
        _env_file=None,
        supabase_url="http://localhost",
        supabase_service_key="k",
        reducto_api_key="k",
        anthropic_api_key="k",
        cohere_api_key="k",
    )
    db = MagicMock()
    db.get_known_scopes.return_value = ["BKW"]
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "DatabaseClient", lambda: db)

    deps = dependencies.build_dependencies()

    assert set(deps) == {"db", "pipeline", "settings"}
    assert isinstance(create_app(**deps), FastAPI)
