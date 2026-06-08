"""
Journey Planner — v1 (doğrudan seferler)
----------------------------------------
"X durağından Y durağına HH:MM'de nasıl giderim?"

v1 yaklaşımı:
  - Sadece doğrudan seferler (aktarmasız)
  - Her aday: X'i ziyaret eden + sonra Y'yi ziyaret eden tek trip
  - 'Earliest arrival' hedefli: Y'ye en erken ulaşan kazanır
  - Top N alternatif döner

v2/v3 planı (ileride):
  - 1 ve 2 aktarmalı seferler (aynı durakta otobüs değiştirme)
  - Yürüme transferleri (aktarma noktaları yakın duraklara)
  - Pareto-optimal (süre vs. aktarma sayısı dengesi)

Algoritma tasarımı:
  Verilen: snapshot_id, from_stop, to_stop, from_time, active_services
  Sorgu = stop_times'ı kendisiyle iç birleştir:
    X_visit: stop_id=from_stop, departure_time ≥ from_time
    Y_visit: aynı trip_id, stop_id=to_stop, stop_sequence > X_visit.stop_sequence
  Filtre: trip.service_id IN active_services
  Sırala: Y_visit.arrival_time artan
  Limit: N

Karmaşıklık: O(|trips visiting X|) self-join, B-tree index ile sub-ms.
"""

from dataclasses import dataclass
from datetime import date as date_cls
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session, aliased

from app.models.gtfs import Route, Stop, StopTime, Trip


@dataclass
class DirectJourney:
    """
    Tek-seferli (doğrudan) bir yolculuk önerisi.
    Bir 'leg' (etap) içerir — aktarma yok.
    """
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

    intermediate_stop_count: int  # Aradaki kaç durak (binişten inişe kaç durak geçilecek)
    duration_seconds: int          # arrival - departure (yaklaşık; HH:MM:SS karşılaştırması)


def _hhmmss_to_seconds(s: str) -> int:
    """
    'HH:MM:SS' → toplam saniye. GTFS'te HH > 23 olabilir (örn '25:30:00'),
    bu yüzden datetime.time kullanmıyoruz.
    """
    parts = s.split(":")
    h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
    return h * 3600 + m * 60 + sec


def find_direct_journeys(
    db: Session,
    snapshot_id: int,
    from_stop: str,
    to_stop: str,
    from_time: str,            # "HH:MM:SS"
    active_service_ids: list[str],
    limit: int = 5,
) -> list[DirectJourney]:
    """
    Doğrudan (tek seferli) yolculukları döndürür.

    SQL özünde:
        SELECT ...
        FROM stop_times X
        JOIN stop_times Y
          ON Y.trip_id = X.trip_id
         AND Y.snapshot_id = X.snapshot_id
         AND Y.stop_sequence > X.stop_sequence
        JOIN trips T ON T.trip_id = X.trip_id AND T.snapshot_id = X.snapshot_id
        JOIN routes R ON R.route_id = T.route_id AND R.snapshot_id = T.snapshot_id
        JOIN stops Sx ON Sx.stop_id = X.stop_id AND Sx.snapshot_id = X.snapshot_id
        JOIN stops Sy ON Sy.stop_id = Y.stop_id AND Sy.snapshot_id = Y.snapshot_id
        WHERE X.snapshot_id = :snap
          AND X.stop_id = :from_stop
          AND X.departure_time >= :from_time
          AND Y.stop_id = :to_stop
          AND T.service_id IN (active_service_ids)
        ORDER BY Y.arrival_time ASC
        LIMIT :limit
    """
    if not active_service_ids:
        return []

    # SQLAlchemy'de tabloya iki kere katılırken aliased() lazım
    X = aliased(StopTime, name="x_visit")  # noqa: N806
    Y = aliased(StopTime, name="y_visit")  # noqa: N806
    Sx = aliased(Stop, name="from_stop")   # noqa: N806
    Sy = aliased(Stop, name="to_stop")     # noqa: N806

    rows = (
        db.query(
            Trip.trip_id,
            Trip.route_id,
            Trip.trip_headsign,
            Route.route_short_name,
            Sx.stop_id.label("from_id"),
            Sx.stop_name.label("from_name"),
            X.stop_sequence.label("from_seq"),
            X.departure_time.label("departure_time"),
            Sy.stop_id.label("to_id"),
            Sy.stop_name.label("to_name"),
            Y.stop_sequence.label("to_seq"),
            Y.arrival_time.label("arrival_time"),
        )
        .join(
            Y,
            and_(
                Y.trip_id == X.trip_id,
                Y.snapshot_id == X.snapshot_id,
                Y.stop_sequence > X.stop_sequence,
                Y.stop_id == to_stop,
            ),
        )
        .join(
            Trip,
            and_(
                Trip.trip_id == X.trip_id,
                Trip.snapshot_id == X.snapshot_id,
            ),
        )
        .outerjoin(
            Route,
            and_(
                Route.route_id == Trip.route_id,
                Route.snapshot_id == Trip.snapshot_id,
            ),
        )
        .outerjoin(
            Sx,
            and_(
                Sx.stop_id == X.stop_id,
                Sx.snapshot_id == X.snapshot_id,
            ),
        )
        .outerjoin(
            Sy,
            and_(
                Sy.stop_id == Y.stop_id,
                Sy.snapshot_id == Y.snapshot_id,
            ),
        )
        .filter(X.snapshot_id == snapshot_id)
        .filter(X.stop_id == from_stop)
        .filter(X.departure_time >= from_time)
        .filter(Trip.service_id.in_(active_service_ids))
        .order_by(Y.arrival_time.asc())
        .limit(limit)
        .all()
    )

    results: list[DirectJourney] = []
    for r in rows:
        dep_sec = _hhmmss_to_seconds(r.departure_time)
        arr_sec = _hhmmss_to_seconds(r.arrival_time)
        results.append(DirectJourney(
            trip_id=r.trip_id,
            route_id=r.route_id,
            route_short_name=r.route_short_name,
            trip_headsign=r.trip_headsign,
            from_stop_id=r.from_id,
            from_stop_name=r.from_name,
            from_stop_sequence=r.from_seq,
            departure_time=r.departure_time,
            to_stop_id=r.to_id,
            to_stop_name=r.to_name,
            to_stop_sequence=r.to_seq,
            arrival_time=r.arrival_time,
            intermediate_stop_count=max(0, r.to_seq - r.from_seq - 1),
            duration_seconds=max(0, arr_sec - dep_sec),
        ))
    return results
