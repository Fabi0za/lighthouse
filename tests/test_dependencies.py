from unittest.mock import MagicMock

import pytest

from fastapi import FastAPI

import app.dependencies as dependencies
from app.config import Settings
from app.main import create_app


def _settings():
    return Settings(
        _env_file=None,
        supabase_url="http://localhost",
        supabase_service_key="k",
        reducto_api_key="k",
        anthropic_api_key="k",
        cohere_api_key="k",
    )


def _db(current_keys):
    db = MagicMock()
    db.get_known_scopes.return_value = ["bkw"]
    db.current_indexing_settings_keys.return_value = current_keys
    return db


def _patch(monkeypatch, db):
    monkeypatch.setattr(dependencies, "get_settings", _settings)
    monkeypatch.setattr(dependencies, "DatabaseClient", lambda: db)


def test_build_dependencies_wires_create_app(monkeypatch):
    from app.settings_rows import indexing_settings_row
    _patch(monkeypatch, _db([indexing_settings_row(_settings())["key"]]))

    deps = dependencies.build_dependencies()

    assert set(deps) == {"db", "pipeline", "settings"}
    assert isinstance(create_app(**deps), FastAPI)


def test_startup_refuses_other_indexing_settings(monkeypatch):
    _patch(monkeypatch, _db(["embed-v4.0-1536-500-50-c1-f1"]))
    with pytest.raises(RuntimeError) as e:
        dependencies.build_dependencies()
    assert "embed-v4.0-1536-500-50-c1-f1" in str(e.value) and "embed-v5.0-pro" in str(e.value)


def test_startup_with_empty_store(monkeypatch):
    _patch(monkeypatch, _db([]))
    assert set(dependencies.build_dependencies()) == {"db", "pipeline", "settings"}

