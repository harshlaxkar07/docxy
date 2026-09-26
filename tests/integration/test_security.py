"""API key authentication and upload limits."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def auth_client(monkeypatch):
    """A client with auth switched on and two valid keys."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEYS", "key-alpha, key-beta")
    from app.main import app

    return TestClient(app)


def test_protected_routes_reject_a_missing_key(auth_client):
    res = auth_client.get("/api/v1/documents")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_protected_routes_reject_a_wrong_key(auth_client):
    res = auth_client.get("/api/v1/documents", headers={"X-API-Key": "not-a-real-key"})
    assert res.status_code == 401


@pytest.mark.parametrize("key", ["key-alpha", "key-beta"])
def test_any_configured_key_is_accepted(auth_client, key):
    res = auth_client.get("/api/v1/documents", headers={"X-API-Key": key})
    assert res.status_code == 200


def test_health_stays_open_for_probes(auth_client):
    """Liveness and readiness must not require credentials."""
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/health/live").status_code == 200
    assert auth_client.get("/health/ready").status_code == 200


def test_auth_without_keys_fails_closed(monkeypatch):
    """Enabling auth but configuring no key must reject, not allow."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "API_KEYS", "")
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/v1/documents", headers={"X-API-Key": "anything"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_auth_disabled_allows_everything(client):
    assert client.get("/api/v1/documents").status_code == 200


def test_cors_never_pairs_wildcard_with_credentials(monkeypatch):
    """Browsers reject "*" together with credentials, so the combination is
    resolved away rather than emitted."""
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setattr(settings, "CORS_ALLOW_CREDENTIALS", True)
    assert settings.cors_allow_credentials is False

    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", "https://app.example.com")
    assert settings.cors_allow_credentials is True
    assert settings.cors_origins == ["https://app.example.com"]


def test_oversized_upload_is_rejected(client, monkeypatch, sample_native_pdf_bytes):
    """The cutoff happens while streaming, before the body is fully buffered."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.0001)  # ~100 bytes

    res = client.post(
        "/api/v1/documents",
        files={"file": ("big.pdf", sample_native_pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_non_pdf_is_rejected(client):
    res = client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] in {"INVALID_PDF_FORMAT", "VALIDATION_ERROR"}


def test_upload_leaves_no_temp_file_behind(client, sample_native_pdf_bytes):
    """The staged temp file is removed whether the upload succeeds or fails."""
    from pathlib import Path

    temp_dir = Path(settings.TEMP_DIR)
    before = set(temp_dir.glob("*.pdf")) if temp_dir.exists() else set()

    client.post(
        "/api/v1/documents",
        files={"file": ("cleanup.pdf", sample_native_pdf_bytes, "application/pdf")},
    )

    after = set(temp_dir.glob("*.pdf")) if temp_dir.exists() else set()
    assert after == before, "a staged upload was left in the temp directory"
