"""
GTFS Parser Servisi
-------------------
Zip dosyasını okur, parse eder, PostgreSQL'e bulk insert yapar.

Akış:
  1. Zip aç → geçici klasöre çıkar
  2. Snapshot kaydı oluştur (tenant_id + label + tarih)
  3. Her GTFS dosyasını pandas ile oku → DataFrame
  4. snapshot_id ve tenant_id kolonlarını ekle
  5. Bulk insert ile DB'ye yaz
  6. Snapshot'ı aktif olarak işaretle
"""

import os
import zipfile
import tempfile
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models.gtfs import (
    GtfsSnapshot, Agency, Route, Stop,
    Calendar, CalendarDate, Trip, StopTime, Shape
)


# ─────────────────────────────────────────
# ANA FONKSİYON — dışarıdan bu çağrılacak
# ─────────────────────────────────────────
def import_gtfs(
    zip_path: str,      # zip dosyasının disk üzerindeki yolu
    tenant_id: str,     # hangi operatör: "burulas", "eshot" vs.
    label: str,         # açıklama: "burulas-2026-nisan"
    db: Session         # SQLAlchemy oturumu
) -> GtfsSnapshot:
    """
    GTFS zip dosyasını okur ve DB'ye yazar.
    Başarılı olursa oluşturulan snapshot'ı döndürür.
    """

    # 1. Snapshot kaydını oluştur
    # Henüz veri yazmadık, sadece "bu import başlıyor" kaydı
    snapshot = _create_snapshot(db, tenant_id, label)
    print(f"📸 Snapshot oluşturuldu: id={snapshot.id}")

    # 2. Zip'i geçici klasöre aç
    # tempfile.mkdtemp() → sistemin temp klasöründe boş bir klasör açar
    # işimiz bitince temizleyeceğiz
    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"📂 Zip açılıyor: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp_dir)

        # 3. Her dosyayı sırayla işle
        # Sıra önemli! Önce bağımsız tablolar, sonra bağımlılar
        _import_agency(tmp_dir, snapshot, db)
        _import_routes(tmp_dir, snapshot, db)
        _import_stops(tmp_dir, snapshot, db)
        _import_calendar(tmp_dir, snapshot, db)
        _import_calendar_dates(tmp_dir, snapshot, db)   # opsiyonel
        _import_trips(tmp_dir, snapshot, db)
        _import_shapes(tmp_dir, snapshot, db)
        _import_stop_times(tmp_dir, snapshot, db)  # en sona bıraktık, en büyük

    # 4. Snapshot'ı aktif yap
    snapshot.is_active = True
    db.commit()
    print(f"✅ Import tamamlandı! Snapshot id={snapshot.id}")

    return snapshot


# ─────────────────────────────────────────
# SNAPSHOT OLUŞTUR
# ─────────────────────────────────────────
def _create_snapshot(db: Session, tenant_id: str, label: str) -> GtfsSnapshot:
    """
    Yeni bir snapshot kaydı oluşturur.
    is_active=False — import bitince True yapacağız.
    Yarıda kalırsa False kalır, bozuk veri aktif olmaz.
    """
    snapshot = GtfsSnapshot(
        tenant_id=tenant_id,
        label=label,
        imported_at=datetime.utcnow().isoformat(),
        is_active=False   # henüz aktif değil
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)  # DB'nin atadığı id'yi al
    return snapshot


# ─────────────────────────────────────────
# YARDIMCI FONKSİYON — bulk insert
# ─────────────────────────────────────────
def _bulk_insert(db: Session, model, records: list[dict]):
    """
    Verilen kayıtları tek seferde DB'ye yazar.

    Neden bulk_insert_mappings?
    - Normal: her satır için ayrı INSERT → yavaş
    - Bulk: tüm satırları tek pakette gönder → hızlı

    1.4M satırlık stop_times için bu fark kritik.
    """
    if not records:
        return
    db.bulk_insert_mappings(model, records)
    db.commit()


# ─────────────────────────────────────────
# YARDIMCI FONKSİYON — DataFrame hazırla
# ─────────────────────────────────────────
def _prepare_df(tmp_dir: str, filename: str, snapshot: GtfsSnapshot) -> pd.DataFrame | None:
    """
    CSV dosyasını okur, snapshot_id ve tenant_id ekler.
    Dosya yoksa None döner (opsiyonel dosyalar için).
    """
    path = os.path.join(tmp_dir, filename)

    if not os.path.exists(path):
        print(f"⚠️  {filename} bulunamadı, atlanıyor")
        return None

    df = pd.read_csv(path, dtype=str)   # dtype=str → tüm kolonları string oku
                                         # stop_id gibi şeyleri int yapmasın
    df = df.where(pd.notna(df), None)   # NaN değerleri None'a çevir (DB için)

    # Her satıra snapshot_id ve tenant_id ekle
    df["snapshot_id"] = snapshot.id
    df["tenant_id"]   = snapshot.tenant_id

    return df


# ─────────────────────────────────────────
# AGENCY
# ─────────────────────────────────────────
def _import_agency(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "agency.txt", snapshot)
    if df is None:
        return

    records = df.rename(columns={
        "agency_id":       "agency_id",
        "agency_name":     "agency_name",
        "agency_url":      "agency_url",
        "agency_timezone": "agency_timezone",
        "agency_lang":     "agency_lang",
    }).to_dict(orient="records")

    _bulk_insert(db, Agency, records)
    print(f"  ✔ agency: {len(records)} kayıt")


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────
def _import_routes(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "routes.txt", snapshot)
    if df is None:
        return

    # Sadece ihtiyacımız olan kolonları al
    kolonlar = ["route_id", "route_short_name", "route_long_name",
                "agency_id", "route_type", "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, Route, records)
    print(f"  ✔ routes: {len(records)} kayıt")


# ─────────────────────────────────────────
# STOPS
# ─────────────────────────────────────────
def _import_stops(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "stops.txt", snapshot)
    if df is None:
        return

    kolonlar = ["stop_id", "stop_name", "stop_lat", "stop_lon",
                "wheelchair_boarding", "location_type",
                "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, Stop, records)
    print(f"  ✔ stops: {len(records)} kayıt")


# ─────────────────────────────────────────
# CALENDAR
# ─────────────────────────────────────────
def _import_calendar(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "calendar.txt", snapshot)
    if df is None:
        return

    kolonlar = ["service_id", "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday",
                "start_date", "end_date", "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, Calendar, records)
    print(f"  ✔ calendar: {len(records)} kayıt")


# ─────────────────────────────────────────
# CALENDAR DATES (opsiyonel — bazı feed'lerde yok)
# ─────────────────────────────────────────
def _import_calendar_dates(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    """
    GTFS calendar_dates.txt — istisna günler (bayram, ekstra çalışma, vs.)
    Dosya opsiyonel; yoksa atlanır ve uygulama yalnızca calendar.txt
    üzerinden çalışır.
    """
    df = _prepare_df(tmp_dir, "calendar_dates.txt", snapshot)
    if df is None:
        return

    kolonlar = ["service_id", "date", "exception_type",
                "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, CalendarDate, records)
    print(f"  ✔ calendar_dates: {len(records)} kayıt")


# ─────────────────────────────────────────
# TRIPS
# ─────────────────────────────────────────
def _import_trips(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "trips.txt", snapshot)
    if df is None:
        return

    kolonlar = ["trip_id", "route_id", "service_id", "direction_id",
                "shape_id", "trip_headsign", "wheelchair_accessible",
                "bikes_allowed", "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, Trip, records)
    print(f"  ✔ trips: {len(records)} kayıt")


# ─────────────────────────────────────────
# SHAPES
# ─────────────────────────────────────────
def _import_shapes(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    df = _prepare_df(tmp_dir, "shapes.txt", snapshot)
    if df is None:
        return

    kolonlar = ["shape_id", "shape_pt_lat", "shape_pt_lon",
                "shape_pt_sequence", "shape_dist_traveled",
                "snapshot_id", "tenant_id"]
    df = df[[k for k in kolonlar if k in df.columns]]

    records = df.to_dict(orient="records")
    _bulk_insert(db, Shape, records)
    print(f"  ✔ shapes: {len(records)} kayıt")


# ─────────────────────────────────────────
# STOP TIMES — en büyük tablo (1.4M satır)
# ─────────────────────────────────────────
def _import_stop_times(tmp_dir: str, snapshot: GtfsSnapshot, db: Session):
    """
    1.4M satırı tek seferde belleğe almak tehlikeli olabilir.
    Bu yüzden chunksize ile parça parça okuyoruz.

    chunksize=50000 → her seferinde 50.000 satır oku, yaz, sil
    Bellek patlaması olmaz.
    """
    path = os.path.join(tmp_dir, "stop_times.txt")
    if not os.path.exists(path):
        print("⚠️  stop_times.txt bulunamadı")
        return

    kolonlar = ["trip_id", "stop_id", "stop_sequence", "arrival_time",
                "departure_time", "pickup_type", "drop_off_type",
                "shape_dist_traveled"]

    toplam = 0
    # chunksize: her iterasyonda 50.000 satır
    for chunk in pd.read_csv(path, dtype=str, chunksize=50_000):
        chunk = chunk.where(pd.notna(chunk), None)
        chunk = chunk[[k for k in kolonlar if k in chunk.columns]]
        chunk["snapshot_id"] = snapshot.id
        chunk["tenant_id"]   = snapshot.tenant_id

        records = chunk.to_dict(orient="records")
        _bulk_insert(db, StopTime, records)
        toplam += len(records)
        print(f"  ✔ stop_times: {toplam} kayıt yazıldı...", end="\r")

    print(f"  ✔ stop_times: {toplam} kayıt toplamda")
