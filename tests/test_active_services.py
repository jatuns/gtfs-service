"""
_active_service_ids() helper'ı için izole birim testler.

Strateji:
  - Geçici bir snapshot oluştur (test sonunda sil)
  - Bu snapshot'a yapay calendar + calendar_dates kayıtları yaz
  - Helper'ı çağırıp doğru sonucu döndürdüğünü doğrula
  - Tüm test verisi commit'lenmeden geri alınabilir mi? Hayır — bulk_insert
    commit gerektiriyor. Bu yüzden temizlik açıkça yapılır (try/finally).
"""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.gtfs import Calendar, CalendarDate, GtfsSnapshot
from app.routers.query_router import _active_service_ids


@pytest.fixture
def temp_snapshot():
    """
    Test boyunca yaşayan bir snapshot + onu kullanan calendar/calendar_dates
    kayıtları. Test bitince hepsi silinir.

    Tarih senaryosu:
      target_date = 2026-04-15 (Çarşamba)
      - svc_normal  : Çarşamba (1), aralık içinde → BASE
      - svc_sunday  : Pazar (1), Çarşamba (0)    → BASE'TE DEĞİL
      - svc_added   : Çarşamba (0) ama exception type=1, date=15 → EKLENDİ
      - svc_removed : Çarşamba (1) ama exception type=2, date=15 → ÇIKARILDI
    """
    db: Session = SessionLocal()
    snap = GtfsSnapshot(
        tenant_id="test_tenant",
        label="active_services_test",
        imported_at="2026-06-05T00:00:00",
        is_active=False,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)

    cals = [
        Calendar(
            snapshot_id=snap.id, tenant_id="test_tenant",
            service_id="svc_normal",
            monday=1, tuesday=1, wednesday=1, thursday=1,
            friday=1, saturday=0, sunday=0,
            start_date="20260401", end_date="20260430",
        ),
        Calendar(
            snapshot_id=snap.id, tenant_id="test_tenant",
            service_id="svc_sunday",
            monday=0, tuesday=0, wednesday=0, thursday=0,
            friday=0, saturday=0, sunday=1,
            start_date="20260401", end_date="20260430",
        ),
        Calendar(
            snapshot_id=snap.id, tenant_id="test_tenant",
            service_id="svc_removed",
            monday=1, tuesday=1, wednesday=1, thursday=1,
            friday=1, saturday=1, sunday=1,
            start_date="20260401", end_date="20260430",
        ),
    ]
    dates = [
        CalendarDate(
            snapshot_id=snap.id, tenant_id="test_tenant",
            service_id="svc_added", date="20260415", exception_type=1,
        ),
        CalendarDate(
            snapshot_id=snap.id, tenant_id="test_tenant",
            service_id="svc_removed", date="20260415", exception_type=2,
        ),
    ]
    db.add_all(cals + dates)
    db.commit()

    try:
        yield db, snap
    finally:
        # Temizlik — çocuklar önce, sonra parent
        db.query(CalendarDate).filter_by(snapshot_id=snap.id).delete()
        db.query(Calendar).filter_by(snapshot_id=snap.id).delete()
        db.delete(snap)
        db.commit()
        db.close()


class TestActiveServiceIds:
    def test_wednesday_normal_service(self, temp_snapshot):
        db, snap = temp_snapshot
        result = set(_active_service_ids(db, snap.id, date(2026, 4, 15)))
        # svc_normal IN, svc_sunday OUT
        assert "svc_normal" in result
        assert "svc_sunday" not in result

    def test_exception_type_1_adds_service(self, temp_snapshot):
        """svc_added Çarşamba normalde çalışmaz; istisna ile eklendi."""
        db, snap = temp_snapshot
        result = set(_active_service_ids(db, snap.id, date(2026, 4, 15)))
        assert "svc_added" in result

    def test_exception_type_2_removes_service(self, temp_snapshot):
        """svc_removed Çarşamba normalde çalışır; istisna ile çıkarıldı."""
        db, snap = temp_snapshot
        result = set(_active_service_ids(db, snap.id, date(2026, 4, 15)))
        assert "svc_removed" not in result

    def test_other_date_unaffected_by_exceptions(self, temp_snapshot):
        """16 Nisan Perşembe — istisnalar yalnız 15 Nisan için tanımlı."""
        db, snap = temp_snapshot
        result = set(_active_service_ids(db, snap.id, date(2026, 4, 16)))
        # Perşembe → svc_normal ve svc_removed çalışır (istisna yok)
        assert "svc_normal" in result
        assert "svc_removed" in result
        # svc_added bu tarihte istisna olmadığı için yine yok
        assert "svc_added" not in result

    def test_outside_date_range(self, temp_snapshot):
        """1 Mart 2026 — calendar aralığı dışında, hiç servis yok."""
        db, snap = temp_snapshot
        result = set(_active_service_ids(db, snap.id, date(2026, 3, 1)))
        # Calendar aralığı 20260401-20260430. Mart hiç servis yok.
        # Sadece istisna ile eklenmiş bir tarih olsa eklerdi ama 1 Mart için yok.
        assert result == set()
