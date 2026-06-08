"""
/journey endpoint testleri.

Senaryolar:
  - Doğrudan sefer bulma + sıralama + filtre
  - 1-aktarmalı sefer bulma
  - max_transfers parametresi
  - min_transfer_seconds parametresi
  - Edge case'ler (geçersiz tarih, eksik param, vs.)

Strateji:
  - _discover_stop_pair: gerçek route'tan iki durak keşfedip
    journey çağırır → hem mini_gtfs hem Burulas verisinde çalışır
"""


def _discover_stop_pair(client, known_route, known_date):
    """Bilinen route'un bir trip'inden ilk ve son durakları çek."""
    r = client.get(
        f"/routes/{known_route['id']}/trips",
        params={"date": known_date, "limit": 1},
    )
    trips = r.json()["trips"]
    assert trips, "Bilinen route için trip yok — fixture eksik"
    trip_id = trips[0]["trip_id"]

    detail = client.get(f"/trips/{trip_id}").json()
    stops = detail["stops"]
    assert len(stops) >= 2, "Trip'in en az 2 durağı olmalı"
    return stops[0]["stop_id"], stops[-1]["stop_id"]


# ─────────────────────────────────────────
# Doğrudan sefer testleri
# ─────────────────────────────────────────

class TestDirectJourney:
    def test_direct_journey_found(self, client, known_route, known_date):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "max_transfers": 0,  # sadece direct
        })
        assert r.status_code == 200
        data = r.json()
        assert data["active_service_count"] > 0
        assert data["journey_count"] > 0

        first = data["journeys"][0]
        assert first["transfer_count"] == 0
        assert len(first["legs"]) == 1

        leg = first["legs"][0]
        assert leg["from_stop_id"] == from_stop
        assert leg["to_stop_id"] == to_stop
        assert leg["from_stop_sequence"] < leg["to_stop_sequence"]
        assert leg["duration_seconds"] > 0

    def test_journeys_sorted_by_arrival(self, client, known_route, known_date):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "limit": 10,
        })
        arrivals = [j["arrival_time"] for j in r.json()["journeys"]]
        assert arrivals == sorted(arrivals)

    def test_from_time_filter(self, client, known_route, known_date):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "10:00:00",
            "date": known_date,
            "limit": 10,
        })
        for j in r.json()["journeys"]:
            assert j["departure_time"] >= "10:00:00"

    def test_max_transfers_zero_returns_only_direct(
        self, client, known_route, known_date
    ):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)
        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "max_transfers": 0,
            "limit": 20,
        })
        for j in r.json()["journeys"]:
            assert j["transfer_count"] == 0

    def test_intermediate_count_consistent(self, client, known_route, known_date):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)
        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
        })
        for j in r.json()["journeys"]:
            for leg in j["legs"]:
                assert leg["intermediate_stop_count"] >= 0
                assert (
                    leg["to_stop_sequence"]
                    - leg["from_stop_sequence"]
                    - 1
                    == leg["intermediate_stop_count"]
                )


# ─────────────────────────────────────────
# 1-aktarmalı sefer testleri
# ─────────────────────────────────────────

class TestOneTransferJourney:
    def test_transfer_legs_are_valid(self, client, known_route, known_date):
        """
        max_transfers=1 ile dönen aktarmalı yolculuklar:
        - 2 leg olmalı
        - leg2.departure_time >= leg1.arrival_time + min_transfer
        - aynı durak: leg1.to_stop_id == leg2.from_stop_id
        - farklı trip: leg1.trip_id != leg2.trip_id
        """
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "max_transfers": 1,
            "min_transfer_seconds": 60,
            "limit": 20,
        })

        for j in r.json()["journeys"]:
            if j["transfer_count"] == 0:
                continue
            assert j["transfer_count"] == 1
            assert len(j["legs"]) == 2
            leg1, leg2 = j["legs"]
            # Aynı aktarma durağı
            assert leg1["to_stop_id"] == leg2["from_stop_id"]
            # Farklı trip
            assert leg1["trip_id"] != leg2["trip_id"]
            # leg1.arrival_time <= leg2.departure_time
            assert leg1["arrival_time"] <= leg2["departure_time"]

    def test_total_duration_consistent(self, client, known_route, known_date):
        """total_duration_seconds = arrival - departure"""
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)
        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "max_transfers": 1,
            "limit": 10,
        })
        for j in r.json()["journeys"]:
            dep = j["departure_time"]
            arr = j["arrival_time"]
            # HH:MM:SS karşılaştırması string'de geçerli (24h içinde)
            assert arr >= dep
            # total duration = arrival - departure (saniye)
            dep_s = sum(int(x) * m for x, m in zip(dep.split(":"), [3600, 60, 1]))
            arr_s = sum(int(x) * m for x, m in zip(arr.split(":"), [3600, 60, 1]))
            assert j["total_duration_seconds"] == arr_s - dep_s


# ─────────────────────────────────────────
# Genel / edge case
# ─────────────────────────────────────────

class TestJourneyEdgeCases:
    def test_unknown_stops_returns_empty(self, client, known_date):
        r = client.get("/journey", params={
            "from_stop": "YOK_BU_DURAK",
            "to_stop": "YOK_BU_DURAK_DA",
            "from_time": "08:00:00",
            "date": known_date,
        })
        assert r.status_code == 200
        assert r.json()["journey_count"] == 0

    def test_date_outside_calendar(self, client):
        r = client.get("/journey", params={
            "from_stop": "D1402",
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": "2027-01-01",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["journey_count"] == 0
        if data["active_service_count"] == 0:
            assert data["note"] is not None

    def test_invalid_date_returns_400(self, client):
        r = client.get("/journey", params={
            "from_stop": "D1402",
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": "bozuk-tarih",
        })
        assert r.status_code == 400

    def test_missing_required_param(self, client):
        r = client.get("/journey", params={
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": "2026-04-15",
        })
        assert r.status_code == 422

    def test_limit_respected(self, client, known_route, known_date):
        from_stop, to_stop = _discover_stop_pair(client, known_route, known_date)
        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "limit": 2,
        })
        assert r.json()["journey_count"] <= 2

    def test_invalid_max_transfers(self, client, known_date):
        """max_transfers > 1 → 422 (v3'te desteklenecek)"""
        r = client.get("/journey", params={
            "from_stop": "D1402",
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": known_date,
            "max_transfers": 2,
        })
        assert r.status_code == 422
