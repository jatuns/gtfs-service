"""
GTFS Veri Modelleri
-------------------
Her class = PostgreSQL'de bir tablo
Her class attribute = tablodaki bir kolon

Neden snapshot_id var?
  Her GTFS import'u yeni bir "snapshot" oluşturur.
  Böylece Nisan 2026 verisi ile Mayıs 2026 verisini
  aynı anda DB'de tutabilirsin. Aktif snapshot'ı
  sorguya filtre olarak geçersin.

Neden tenant_id var?
  Bu servis Bursa, İzmir, Ankara gibi farklı
  şehirlere aynı anda hizmet verebilir.
  tenant_id = "burulas" | "eshot" | "iett" gibi.
  Her sorgu tenant_id ile filtrelenir.
"""

from sqlalchemy import (
    Column, String, Integer, Float,
    Boolean, Date, Time, ForeignKey, Index
)
from app.database import Base


# ─────────────────────────────────────────
# 1. SNAPSHOT — Her import'un kimliği
# ─────────────────────────────────────────
class GtfsSnapshot(Base):
    __tablename__ = "gtfs_snapshots"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id   = Column(String, nullable=False)        # hangi şehir/operatör
    label       = Column(String, nullable=False)        # örn: "burulas-2026-april"
    imported_at = Column(String, nullable=False)        # import tarihi (ISO string)
    is_active   = Column(Boolean, default=False)        # aktif snapshot mı?

    def __repr__(self):
        return f"<Snapshot {self.id} | {self.tenant_id} | {self.label}>"


# ─────────────────────────────────────────
# 2. AGENCY — Operatör (BURULAS)
# ─────────────────────────────────────────
class Agency(Base):
    __tablename__ = "agencies"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id   = Column(String, nullable=False)

    agency_id   = Column(String)                        # GTFS'teki agency_id (örn: "1")
    agency_name = Column(String)
    agency_url  = Column(String)
    agency_timezone = Column(String)
    agency_lang = Column(String)


# ─────────────────────────────────────────
# 3. ROUTE — Hat (101, 202, 38B gibi)
# ─────────────────────────────────────────
class Route(Base):
    __tablename__ = "routes"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id      = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id        = Column(String, nullable=False)

    route_id         = Column(String, nullable=False)   # GTFS'teki ID, string tutuyoruz
    route_short_name = Column(String)                   # "101", "38B"
    route_long_name  = Column(String)                   # "Armutkoy Mh. - Ring"
    agency_id        = Column(String)
    route_type       = Column(Integer)                  # 3 = otobüs

    # Sık sorgulanan kolonlara index — sorguları hızlandırır
    __table_args__ = (
        Index("ix_routes_snapshot_route", "snapshot_id", "route_id"),
        Index("ix_routes_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────
# 4. STOP — Durak
# ─────────────────────────────────────────
class Stop(Base):
    __tablename__ = "stops"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id         = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id           = Column(String, nullable=False)

    # ⚠️ stop_id Burulas'ta string: "D13-136-S" formatında — INTEGER YAPMA!
    stop_id             = Column(String, nullable=False)
    stop_name           = Column(String)
    stop_lat            = Column(Float)
    stop_lon            = Column(Float)
    wheelchair_boarding = Column(Integer, default=0)
    location_type       = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_stops_snapshot_stop", "snapshot_id", "stop_id"),
        Index("ix_stops_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────
# 5. CALENDAR — Hangi servis hangi gün çalışır
# ─────────────────────────────────────────
class Calendar(Base):
    __tablename__ = "calendars"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id   = Column(String, nullable=False)

    service_id  = Column(String, nullable=False)
    monday      = Column(Integer)   # 1 = çalışır, 0 = çalışmaz
    tuesday     = Column(Integer)
    wednesday   = Column(Integer)
    thursday    = Column(Integer)
    friday      = Column(Integer)
    saturday    = Column(Integer)
    sunday      = Column(Integer)
    start_date  = Column(String)    # "20260401" formatında geliyor
    end_date    = Column(String)


# ─────────────────────────────────────────
# 6. TRIP — Sefer (bir hat üzerindeki yolculuk)
# ─────────────────────────────────────────
class Trip(Base):
    __tablename__ = "trips"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id          = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id            = Column(String, nullable=False)

    # ⚠️ trip_id string: "101-0-127-06:00:00-1026" formatında
    trip_id              = Column(String, nullable=False)
    route_id             = Column(String, nullable=False)   # Route ile join için
    service_id           = Column(String)                   # Calendar ile join için
    direction_id         = Column(Integer)                  # 0 veya 1 (gidiş/dönüş)
    shape_id             = Column(String)
    trip_headsign        = Column(String)                   # Ekranda görünen yazı
    wheelchair_accessible = Column(Integer, default=0)
    bikes_allowed        = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_trips_snapshot_trip", "snapshot_id", "trip_id"),
        Index("ix_trips_snapshot_route", "snapshot_id", "route_id"),
        Index("ix_trips_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────
# 7. STOP TIME — Sefer × Durak × Saat (en büyük tablo: 1.4M+ satır)
# ─────────────────────────────────────────
class StopTime(Base):
    __tablename__ = "stop_times"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id         = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id           = Column(String, nullable=False)

    trip_id             = Column(String, nullable=False)    # hangi sefer
    stop_id             = Column(String, nullable=False)    # hangi durak
    stop_sequence       = Column(Integer)                   # kaçıncı durak
    arrival_time        = Column(String)                    # "06:00:00" — TIME yerine String
    departure_time      = Column(String)                    # çünkü "25:30:00" olabilir (gece yarısı sonrası)
    pickup_type         = Column(Integer, default=0)
    drop_off_type       = Column(Integer, default=0)
    shape_dist_traveled = Column(Float)

    # Bu tablo üzerinde çok sorgu yapılacak — index kritik
    __table_args__ = (
        Index("ix_stop_times_trip", "snapshot_id", "trip_id"),
        Index("ix_stop_times_stop", "snapshot_id", "stop_id"),
        Index("ix_stop_times_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────
# 8. SHAPE — Güzergah geometrisi (harita çizmek için)
# ─────────────────────────────────────────
class Shape(Base):
    __tablename__ = "shapes"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id         = Column(Integer, ForeignKey("gtfs_snapshots.id"), nullable=False)
    tenant_id           = Column(String, nullable=False)

    shape_id            = Column(String, nullable=False)
    shape_pt_lat        = Column(Float)
    shape_pt_lon        = Column(Float)
    shape_pt_sequence   = Column(Integer)
    shape_dist_traveled = Column(Float)

    __table_args__ = (
        Index("ix_shapes_snapshot_shape", "snapshot_id", "shape_id"),
    )
