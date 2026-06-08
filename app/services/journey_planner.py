"""
Journey Planner — v2 (doğrudan + 1 aktarmalı)
---------------------------------------------
"X durağından Y durağına HH:MM'de nasıl giderim?"

v1 (doğrudan):
  - Aynı trip hem X'i hem Y'yi sırayla ziyaret eder.
  - SQL self-join ile bulunur.

v2 (1 aktarmalı):
  - X → M (leg1, trip1) + M → Y (leg2, trip2)
  - M = aynı stop_id (otobüs değiştirilir, yürünmez)
  - leg2.departure_time ≥ leg1.arrival_time + min_transfer_seconds
  - leg1.trip ≠ leg2.trip (aynı trip → direct sayılır)
  - M ∉ {X, Y} (mantıksız aktarma elenir)

İleri (v3):
  - 2+ aktarmalı seferler (RAPTOR / CSA algoritmaları)
  - Yürüme transferleri (yakın stop_id'ler arasında)
  - Pareto-optimal cevaplar

Tasarım kararı:
  - leg1 ve leg2 ayrı SQL sorguları (toplam 2 query)
  - Aralarındaki match Python'da yapılır → 'cartesian explosion'
    DB'de değil, ROM'da (sınırlı sayıda satır)
  - leg1 sonuçlarına LIMIT konulur (200) — yoksa popular durak +
    1.4M satırlı stop_times kombinasyonu patlatabilir
"""

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session, aliased

from app.models.gtfs import Route, Stop, StopTime, Trip


# ─────────────────────────────────────────
# Veri tipleri
# ─────────────────────────────────────────

@dataclass
class JourneyLeg:
    """Tek seferli (aktarmasız) bir etap."""
    trip_id: str
    route_id: str
    route_short_name: Optional[str]
    trip_headsign: Optional[str]

    from_stop_id: str
    from_stop_name: Optional[str]
    from_stop_sequence: int
    departure_time: str

    to_stop_id: str
    to_stop_name: Optional[str]
    to_stop_sequence: int
    arrival_time: str

    intermediate_stop_count: int
    duration_seconds: int


@dataclass
class Journey:
    """1 veya birden çok etap içeren tam yolculuk."""
    legs: list[JourneyLeg] = field(default_factory=list)

    @property
    def transfer_count(self) -> int:
        return max(0, len(self.legs) - 1)

    @property
    def departure_time(self) -> str:
        return self.legs[0].departure_time

    @property
    def arrival_time(self) -> str:
        return self.legs[-1].arrival_time

    @property
    def total_duration_seconds(self) -> int:
        return _hhmmss_to_seconds(self.arrival_time) - _hhmmss_to_seconds(self.departure_time)


# ─────────────────────────────────────────
# Yardımcı
# ─────────────────────────────────────────

def _hhmmss_to_seconds(s: str) -> int:
    """
    'HH:MM:SS' → toplam saniye. GTFS'te HH > 23 olabilir ('25:30:00').
    """
    parts = s.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def _seconds_to_hhmmss(secs: int) -> str:
    """Tersine — Python tarafında aktarma süresini saate çevirmek için."""
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ─────────────────────────────────────────
# v1 — Doğrudan seferler
# ─────────────────────────────────────────

def find_direct_journeys(
    db: Session,
    snapshot_id: int,
    from_stop: str,
    to_stop: str,
    from_time: str,
    active_service_ids: list[str],
    limit: int = 5,
) -> list[Journey]:
    """
    Tek seferli (aktarmasız) yolculuklar — Y'ye en erken ulaşan ilk N.

    SQL: stop_times self-join (X_visit ⨝ Y_visit aynı trip, sequence sıralı).
    """
    if not active_service_ids:
        return []

    X = aliased(StopTime, name="x_visit")   # noqa: N806
    Y = aliased(StopTime, name="y_visit")   # noqa: N806
    Sx = aliased(Stop, name="from_stop")    # noqa: N806
    Sy = aliased(Stop, name="to_stop")      # noqa: N806

    rows = (
        db.query(
            Trip.trip_id,
            Trip.route_id,
            Trip.trip_headsign,
            Route.route_short_name,
            Sx.stop_id.label("from_id"),
            Sx.stop_name.label("from_name"),
            X.stop_sequence.label("from_seq"),
            X.departure_time.label("dep_time"),
            Sy.stop_id.label("to_id"),
            Sy.stop_name.label("to_name"),
            Y.stop_sequence.label("to_seq"),
            Y.arrival_time.label("arr_time"),
        )
        .join(Y, and_(
            Y.trip_id == X.trip_id,
            Y.snapshot_id == X.snapshot_id,
            Y.stop_sequence > X.stop_sequence,
            Y.stop_id == to_stop,
        ))
        .join(Trip, and_(
            Trip.trip_id == X.trip_id,
            Trip.snapshot_id == X.snapshot_id,
        ))
        .outerjoin(Route, and_(
            Route.route_id == Trip.route_id,
            Route.snapshot_id == Trip.snapshot_id,
        ))
        .outerjoin(Sx, and_(
            Sx.stop_id == X.stop_id,
            Sx.snapshot_id == X.snapshot_id,
        ))
        .outerjoin(Sy, and_(
            Sy.stop_id == Y.stop_id,
            Sy.snapshot_id == Y.snapshot_id,
        ))
        .filter(X.snapshot_id == snapshot_id)
        .filter(X.stop_id == from_stop)
        .filter(X.departure_time >= from_time)
        .filter(Trip.service_id.in_(active_service_ids))
        .order_by(Y.arrival_time.asc())
        .limit(limit)
        .all()
    )

    journeys: list[Journey] = []
    for r in rows:
        leg = JourneyLeg(
            trip_id=r.trip_id,
            route_id=r.route_id,
            route_short_name=r.route_short_name,
            trip_headsign=r.trip_headsign,
            from_stop_id=r.from_id,
            from_stop_name=r.from_name,
            from_stop_sequence=r.from_seq,
            departure_time=r.dep_time,
            to_stop_id=r.to_id,
            to_stop_name=r.to_name,
            to_stop_sequence=r.to_seq,
            arrival_time=r.arr_time,
            intermediate_stop_count=max(0, r.to_seq - r.from_seq - 1),
            duration_seconds=max(0, _hhmmss_to_seconds(r.arr_time) - _hhmmss_to_seconds(r.dep_time)),
        )
        journeys.append(Journey(legs=[leg]))
    return journeys


# ─────────────────────────────────────────
# v2 — 1 aktarmalı seferler
# ─────────────────────────────────────────

# Performans koruyucusu: X'ten kalkan trip'lerin sonraki tüm stop'larını
# çekerken kaç satıra kadar gideceğimizi sınırlamak (popüler durakta
# milyonlarca leg1 oluşmasın). 200 çoğu senaryo için yeterli.
_LEG1_HARD_LIMIT = 200


def _query_leg1_candidates(
    db: Session, snapshot_id: int, from_stop: str, from_time: str,
    active_service_ids: list[str], exclude_stops: set[str],
) -> list:
    """
    X'ten gidip herhangi bir M'ye varan tüm (trip, M) çiftleri.
    Sıralama: M'ye en erken varış.
    """
    X = aliased(StopTime, name="x_visit")   # noqa: N806
    M = aliased(StopTime, name="m_visit")   # noqa: N806

    return (
        db.query(
            Trip.trip_id.label("trip_id"),
            Trip.route_id.label("route_id"),
            Trip.trip_headsign.label("headsign"),
            Route.route_short_name.label("short_name"),
            X.stop_sequence.label("x_seq"),
            X.departure_time.label("x_dep"),
            M.stop_id.label("m_id"),
            M.stop_sequence.label("m_seq"),
            M.arrival_time.label("m_arr"),
        )
        .join(M, and_(
            M.trip_id == X.trip_id,
            M.snapshot_id == X.snapshot_id,
            M.stop_sequence > X.stop_sequence,
            ~M.stop_id.in_(exclude_stops),
        ))
        .join(Trip, and_(
            Trip.trip_id == X.trip_id,
            Trip.snapshot_id == X.snapshot_id,
        ))
        .outerjoin(Route, and_(
            Route.route_id == Trip.route_id,
            Route.snapshot_id == Trip.snapshot_id,
        ))
        .filter(X.snapshot_id == snapshot_id)
        .filter(X.stop_id == from_stop)
        .filter(X.departure_time >= from_time)
        .filter(Trip.service_id.in_(active_service_ids))
        .order_by(M.arrival_time.asc())
        .limit(_LEG1_HARD_LIMIT)
        .all()
    )


def _query_leg2_candidates(
    db: Session, snapshot_id: int, m_ids: list[str], to_stop: str,
    earliest_m_departure: str, active_service_ids: list[str],
) -> list:
    """
    Bir M kümesinden Y'ye giden tüm (trip, M, Y) sıraları.
    """
    M2 = aliased(StopTime, name="m_dep")    # noqa: N806
    Y = aliased(StopTime, name="y_visit")   # noqa: N806

    return (
        db.query(
            Trip.trip_id.label("trip_id"),
            Trip.route_id.label("route_id"),
            Trip.trip_headsign.label("headsign"),
            Route.route_short_name.label("short_name"),
            M2.stop_id.label("m_id"),
            M2.stop_sequence.label("m_seq"),
            M2.departure_time.label("m_dep"),
            Y.stop_sequence.label("y_seq"),
            Y.arrival_time.label("y_arr"),
        )
        .join(Y, and_(
            Y.trip_id == M2.trip_id,
            Y.snapshot_id == M2.snapshot_id,
            Y.stop_sequence > M2.stop_sequence,
            Y.stop_id == to_stop,
        ))
        .join(Trip, and_(
            Trip.trip_id == M2.trip_id,
            Trip.snapshot_id == M2.snapshot_id,
        ))
        .outerjoin(Route, and_(
            Route.route_id == Trip.route_id,
            Route.snapshot_id == Trip.snapshot_id,
        ))
        .filter(M2.snapshot_id == snapshot_id)
        .filter(M2.stop_id.in_(m_ids))
        .filter(M2.departure_time >= earliest_m_departure)
        .filter(Trip.service_id.in_(active_service_ids))
        .all()
    )


def find_one_transfer_journeys(
    db: Session,
    snapshot_id: int,
    from_stop: str,
    to_stop: str,
    from_time: str,
    active_service_ids: list[str],
    min_transfer_seconds: int = 120,
    limit: int = 5,
) -> list[Journey]:
    """
    1 aktarmalı yolculuklar.

    Algoritma:
      1) X'ten kalkıp her olası M durağına varan trip'leri çek (leg1)
      2) M'lerin set'inden Y'ye giden trip'leri çek (leg2)
      3) (leg1, leg2) çiftleri arasında:
         - leg2.m_dep ≥ leg1.m_arr + min_transfer_seconds
         - leg2.trip ≠ leg1.trip
         olanları topla
      4) Y'ye en erken ulaşana göre sırala, top limit
    """
    if not active_service_ids:
        return []

    # 1) leg1: X → M
    leg1_rows = _query_leg1_candidates(
        db, snapshot_id, from_stop, from_time, active_service_ids,
        exclude_stops={from_stop, to_stop},
    )
    if not leg1_rows:
        return []

    # M durakları set'i
    m_ids = sorted({r.m_id for r in leg1_rows})

    # Performans için: leg2'yi sorgularken aşağıda kullanılacak en erken kalkışı
    # belirle (en erken leg1.m_arr - henüz transfer_seconds eklenmemiş; precise
    # check Python tarafında yapılır)
    earliest_m_arr = min(r.m_arr for r in leg1_rows)

    # 2) leg2: M → Y
    leg2_rows = _query_leg2_candidates(
        db, snapshot_id, m_ids, to_stop, earliest_m_arr, active_service_ids,
    )
    if not leg2_rows:
        return []

    # 3) Match
    # leg1 rows'u M_id ile gruplayıp Python tarafında kombinasyon yapalım
    # Aynı M için birden fazla leg1 olabilir; her birini değerlendireceğiz
    # (farklı trip → farklı M_arr).
    journeys: list[Journey] = []
    seen_signatures: set[tuple[str, str]] = set()

    # Indeksleme: M_id → leg1 listesi
    leg1_by_m: dict[str, list] = {}
    for r in leg1_rows:
        leg1_by_m.setdefault(r.m_id, []).append(r)

    for r2 in leg2_rows:
        candidates = leg1_by_m.get(r2.m_id, [])
        for r1 in candidates:
            # Aynı trip → direct, atla
            if r1.trip_id == r2.trip_id:
                continue
            # Transfer süresi yeterli mi?
            transfer = _hhmmss_to_seconds(r2.m_dep) - _hhmmss_to_seconds(r1.m_arr)
            if transfer < min_transfer_seconds:
                continue

            # Aynı (trip1, trip2) çifti aynı M ile birden çok kez görünmesin
            sig = (r1.trip_id, r2.trip_id)
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            leg1 = JourneyLeg(
                trip_id=r1.trip_id,
                route_id=r1.route_id,
                route_short_name=r1.short_name,
                trip_headsign=r1.headsign,
                from_stop_id=from_stop,
                from_stop_name=None,
                from_stop_sequence=r1.x_seq,
                departure_time=r1.x_dep,
                to_stop_id=r1.m_id,
                to_stop_name=None,
                to_stop_sequence=r1.m_seq,
                arrival_time=r1.m_arr,
                intermediate_stop_count=max(0, r1.m_seq - r1.x_seq - 1),
                duration_seconds=max(0, _hhmmss_to_seconds(r1.m_arr) - _hhmmss_to_seconds(r1.x_dep)),
            )
            leg2 = JourneyLeg(
                trip_id=r2.trip_id,
                route_id=r2.route_id,
                route_short_name=r2.short_name,
                trip_headsign=r2.headsign,
                from_stop_id=r2.m_id,
                from_stop_name=None,
                from_stop_sequence=r2.m_seq,
                departure_time=r2.m_dep,
                to_stop_id=to_stop,
                to_stop_name=None,
                to_stop_sequence=r2.y_seq,
                arrival_time=r2.y_arr,
                intermediate_stop_count=max(0, r2.y_seq - r2.m_seq - 1),
                duration_seconds=max(0, _hhmmss_to_seconds(r2.y_arr) - _hhmmss_to_seconds(r2.m_dep)),
            )
            journeys.append(Journey(legs=[leg1, leg2]))

    # 4) Sırala + limit
    journeys.sort(key=lambda j: (j.arrival_time, j.total_duration_seconds))
    return journeys[:limit]


# ─────────────────────────────────────────
# Üst düzey planlayıcı — birleştirici
# ─────────────────────────────────────────

def plan_journeys(
    db: Session,
    snapshot_id: int,
    from_stop: str,
    to_stop: str,
    from_time: str,
    active_service_ids: list[str],
    max_transfers: int = 1,
    min_transfer_seconds: int = 120,
    limit: int = 5,
) -> list[Journey]:
    """
    Tüm aday yolculukları (direct + 1-transfer) bul, birleştir, sırala.

    max_transfers=0 → sadece direct
    max_transfers=1 → direct + 1-transfer
    (max_transfers≥2 ileride desteklenecek)
    """
    candidates: list[Journey] = []

    # Direct her zaman tercih edilir → onları her durumda hesapla
    candidates.extend(find_direct_journeys(
        db, snapshot_id, from_stop, to_stop, from_time, active_service_ids,
        limit=limit,
    ))

    if max_transfers >= 1:
        candidates.extend(find_one_transfer_journeys(
            db, snapshot_id, from_stop, to_stop, from_time, active_service_ids,
            min_transfer_seconds=min_transfer_seconds,
            limit=limit,
        ))

    # Birleşik sıralama: arrival_time, sonra transfer_count, sonra duration
    candidates.sort(key=lambda j: (
        j.arrival_time,
        j.transfer_count,
        j.total_duration_seconds,
    ))

    # Aynı 'signature' (legs'in trip_id'leri) bir kere görünsün
    seen: set[tuple] = set()
    deduped: list[Journey] = []
    for j in candidates:
        sig = tuple(leg.trip_id for leg in j.legs)
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(j)
        if len(deduped) >= limit:
            break

    return deduped
