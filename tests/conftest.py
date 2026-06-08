"""
Pytest conftest
---------------
Tüm test dosyalarının paylaştığı fixture'lar burada.

Strateji:
  - Mock yok. Gerçek DB'ye karşı koşuyoruz.
  - Endpoint'ler read-only (POST /import/ hariç) → veri bozulmaz.
  - DATABASE_URL .env dosyasından okunur (database.py zaten okuyor).

Veri kaynağı (otomatik tespit):
  - Lokalde Burulas Nisan 2026 snapshot'ı varsa → onu kullanır
  - CI'da boş DB ile başlandığında → tests/fixtures/mini_gtfs/'i
    sıkıştırıp POST /import/ benzeri akışla yükler (auto-fixture)

Çalıştırma (Mac/lokal):
  source venv/bin/activate
  pip install -r requirements-dev.txt
  pytest -v
"""

import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.gtfs import GtfsSnapshot
from app.services.gtfs_parser import import_gtfs


TENANT_ID = "burulas"
_MINI_GTFS_DIR = Path(__file__).parent / "fixtures" / "mini_gtfs"


@pytest.fixture(scope="session", autouse=True)
def ensure_test_data():
    """
    Test başlamadan ÖNCE veri olmasını garanti eder.

    Akış:
      1. DB'ye bak: TENANT_ID için aktif (is_active=True) snapshot var mı?
      2. Varsa (lokal geliştirici, Burulas verisi yüklü) → hiçbir şey yapma
      3. Yoksa (CI, taze DB) → mini_gtfs/'i sıkıştırıp import et

    Bu sayede:
      - Lokalde testler senin Burulas verine karşı koşar (gerçek dünya)
      - CI'da küçük sentetik fixture ile aynı 40 test geçer
      - İki ortam da aynı 'KNOWN_*' sabitlerinden faydalanır
    """
    # CI'da tabloları kur (lifespan henüz tetiklenmedi).
    # Lokalde idempotent — tablolar zaten var, dokunmaz.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = (
            db.query(GtfsSnapshot)
            .filter(GtfsSnapshot.tenant_id == TENANT_ID)
            .filter(GtfsSnapshot.is_active == True)  # noqa: E712
            .first()
        )
        if existing is not None:
            # Lokal geliştirici makinesi — gerçek veriyle çalış
            return

        # CI / boş DB — mini fixture'ı sıkıştırıp import et
        with tempfile.NamedTemporaryFile(
            suffix=".zip", delete=False
        ) as tmp:
            zip_path = tmp.name

        try:
            with zipfile.ZipFile(zip_path, "w") as zf:
                for txt in sorted(_MINI_GTFS_DIR.glob("*.txt")):
                    zf.write(txt, arcname=txt.name)

            import_gtfs(
                zip_path=zip_path,
                tenant_id=TENANT_ID,
                label="ci-mini-fixture",
                db=db,
            )
        finally:
            Path(zip_path).unlink(missing_ok=True)
    finally:
        db.close()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """
    Tüm testlerin paylaştığı HTTP client.
    Session scope: her test için tekrar oluşturulmaz, hızlı.
    """
    return TestClient(app)


# ─── Bilinen "altın" test verileri ───
# Bu sabitleri test dosyalarında kullanıyoruz. Hem Burulas gerçek verisi
# hem de mini_gtfs sentetik fixture'ı bu değerlerle uyumlu olacak şekilde
# tasarlandı. Veri değişirse buradan tek noktada güncellenir.

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
