import asyncio

import pytest

from app import youtube


def test_exchange_code_reports_google_error(monkeypatch):
    class FakeResponse:
        status_code = 400
        text = '{"error":"invalid_grant"}'

        def json(self):
            return {"error": "invalid_grant"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data):
            return FakeResponse()

    monkeypatch.setattr(youtube.httpx, "AsyncClient", lambda timeout=30: FakeClient())
    monkeypatch.setattr(youtube.config, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(youtube.config, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(youtube.config, "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/callback/youtube")

    with pytest.raises(RuntimeError, match="Google Token-Tausch fehlgeschlagen"):
        asyncio.run(youtube.exchange_code("dummy-code"))
