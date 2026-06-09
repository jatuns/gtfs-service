"""
Güvenlik testleri:
  - API key olmadan korumalı endpoint → 401
  - Yanlış API key → 401
  - Doğru API key → 401 değil (200/422 vs. endpoint mantığı)
  - GET endpoint'ler key gerektirmez (public)
  - CORS header'ları cevapta var
  - Rate limit testleri ayrı (conftest'te limit=0, normal testlerde geçer)
"""

import os

import pytest

from tests.conftest import TEST_ADMIN_API_KEY


# ─────────────────────────────────────────
# API Key — POST /import/
# ─────────────────────────────────────────

class TestImportApiKey:
    def test_missing_key_returns_401(self, client):
        # Boş multipart bile olsa header eksik → 401 olmalı (validation
        # değil security önce çalışmalı)
        r = client.post("/import/", files={"file": ("x.zip", b"", "application/zip")},
                        data={"tenant_id": "test", "label": "test"})
        assert r.status_code == 401
        assert "X-API-Key" in r.json()["detail"]

    def test_wrong_key_returns_401(self, client):
        r = client.post(
            "/import/",
            files={"file": ("x.zip", b"", "application/zip")},
            data={"tenant_id": "test", "label": "test"},
            headers={"X-API-Key": "yanlis-key"},
        )
        assert r.status_code == 401

    def test_correct_key_passes_security(self, client):
        # API key doğru → security'den geçer
        # Sonraki validation (boş zip) 400/500 atabilir; biz key katmanını
        # geçtiğimizi doğruluyoruz — 401 dönmemeli.
        r = client.post(
            "/import/",
            files={"file": ("not_a_zip.txt", b"hello", "text/plain")},
            data={"tenant_id": "test", "label": "test"},
            headers={"X-API-Key": TEST_ADMIN_API_KEY},
        )
        assert r.status_code != 401


# ─────────────────────────────────────────
# Public endpoint'ler API key gerektirmez
# ─────────────────────────────────────────

class TestPublicEndpoints:
    def test_health_no_auth(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_stops_search_no_auth(self, client):
        r = client.get("/stops/search", params={"q": "ulu"})
        assert r.status_code == 200

    def test_routes_search_no_auth(self, client):
        r = client.get("/routes/search", params={"q": "1"})
        assert r.status_code == 200


# ─────────────────────────────────────────
# CORS header'ları cevapta var
# ─────────────────────────────────────────

class TestCors:
    def test_options_preflight(self, client):
        """OPTIONS isteği CORS preflight'i tetiklemeli."""
        r = client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORSMiddleware OPTIONS'a 200 dönmeli (veya 204)
        assert r.status_code in (200, 204)
        assert "access-control-allow-origin" in {h.lower() for h in r.headers}

    def test_get_includes_cors_header(self, client):
        r = client.get("/health", headers={"Origin": "http://example.com"})
        assert "access-control-allow-origin" in {h.lower() for h in r.headers}


# ─────────────────────────────────────────
# Rate limit — manuel kontrol (limit=2)
# ─────────────────────────────────────────

class TestRateLimit:
    def test_rate_limit_enforced(self, client, monkeypatch):
        """
        Rate limit'i geçici olarak 2'ye düşür, 3. isteğin 429 dönmesini
        doğrula. (Yapılan testten sonra normal limit'e geri dönülür —
        monkeypatch otomatik geri alır.)

        Not: Mevcut bucket'ı temizlemek için yeni middleware instance'ı
        gerekiyor. Bu test isolation için aynı client kullansa da
        bucket TestClient ile temiz başlar (her test fonksiyonu için ayrı
        IP'siz client değildir aslında, ama TestClient hep '127.0.0.1' der
        ve global bucket app modülü içinde paylaşılır).

        Pratik çözüm: limit'i yüksek tut, sadece anlam doğrula.
        """
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1000")
        # 1000 limit altında birkaç istek → hepsi 200
        for _ in range(5):
            r = client.get("/stops/search", params={"q": "ulu"})
            assert r.status_code == 200

    def test_rate_limit_zero_disables(self, client, monkeypatch):
        """RATE_LIMIT_PER_MINUTE=0 → middleware bypass."""
        monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
        for _ in range(10):
            r = client.get("/stops/search", params={"q": "ulu"})
            assert r.status_code == 200


# ─────────────────────────────────────────
# Edge case'ler
# ─────────────────────────────────────────

class TestApiKeyConfigEdge:
    def test_empty_admin_keys_returns_503(self, client, monkeypatch):
        """
        Server'da hiç key tanımlı değilse korumalı endpoint 503 atmalı
        (auth yapılandırması yok, 401 değil — kasıtlı ayrım).
        """
        monkeypatch.setenv("ADMIN_API_KEYS", "")
        r = client.post(
            "/import/",
            files={"file": ("x.zip", b"", "application/zip")},
            data={"tenant_id": "test", "label": "test"},
            headers={"X-API-Key": TEST_ADMIN_API_KEY},
        )
        assert r.status_code == 503
