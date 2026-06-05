"""
Pytest conftest
---------------
Tüm test dosyalarının paylaştığı fixture'lar burada.

Strateji:
  - Mock yok. Gerçek DB'ye (Burulas Nisan 2026) karşı koşuyoruz.
  - Endpoint'ler read-only (POST /import/ hariç) → veri bozulmaz.
  - DATABASE_URL .env dosyasından okunur (database.py zaten okuyor).

Çalıştırma (Mac/lokal):
  source .venv/bin/activate
  pip install -r requirements-dev.txt
  pytest -v
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """
    Tüm testlerin paylaştığı HTTP client.
    Session scope: her test için tekrar oluşturulmaz, hızlı.
    """
    return TestClient(app)


# ─── Bilinen "altın" test verileri ───
# Bu sabitleri test dosyalarında kullanıyoruz. Burulas Nisan 2026 verisinde
# kararlı oldukları doğrulanmıştır. Veri değişirse buradan tek noktada
# güncellenir.

TENANT_ID = "burulas"

# ULUCAMI — Bursa merkez, çok sefer geçiyor
KNOWN_STOP_ID = "D0052"
KNOWN_STOP_NAME = "ULUCAMI"
KNOWN_STOP_LAT = 40.18351
KNOWN_STOP_LON = 29.06127

# 15 — Ring hattı (Armutköy)
KNOWN_ROUTE_ID = "15"
KNOWN_ROUTE_SHORT = "15"

# Nisan 2026 verisinde geçerli tarih (Çarşamba)
KNOWN_DATE = "2026-04-15"


@pytest.fixture
def tenant_id() -> str:
    return TENANT_ID


@pytest.fixture
def known_stop() -> dict:
    return {
        "id": KNOWN_STOP_ID,
        "name": KNOWN_STOP_NAME,
        "lat": KNOWN_STOP_LAT,
        "lon": KNOWN_STOP_LON,
    }


@pytest.fixture
def known_route() -> dict:
    return {
        "id": KNOWN_ROUTE_ID,
        "short_name": KNOWN_ROUTE_SHORT,
    }


@pytest.fixture
def known_date() -> str:
    return KNOWN_DATE
