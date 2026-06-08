"""
/journey endpoint testleri.

Senaryolar:
  - Doğrudan sefer bulma (mini_gtfs + Burulas için ortak)
  - 'Earliest arrival' sıralaması doğru mu
  - Tarih dışı → boş + not
  - Yön kontrolü (X.seq < Y.seq) — ters yön sefer dönmemeli
  - 422 (eksik parametre, geçersiz)
"""


def _discover_stop_pair(client, known_route, known_date):
    """
    Bilinen route'un bir trip'inden ilk ve son durağı keşfeder.
    Bu, hem mini_gtfs'te hem gerçek Burulas verisinde çalışan bir
    journey örneği üretir — sabit ID'lere bel bağlamayız.

    Return: (from_stop_id, to_stop_id, trip_start_time)
    """
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
    return stops[0]["stop_id"], stops[-1]["stop_id"], stops[0]["departure_time"]


class TestJourneyPlanner:
    def test_direct_journey_found(self, client, known_route, known_date):
        """
        Bilinen route'un bir trip'i üzerindeki iki durak için journey arar.
        Bu trip zaten bu iki durağı (sırayla) ziyaret ettiği için
        en az 1 doğrudan sefer bulunmalı.
        """
        from_stop, to_stop, _ = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["active_service_count"] > 0
        assert data["journey_count"] > 0

        first = data["direct_journeys"][0]
        assert first["from_stop_id"] == from_stop
        assert first["to_stop_id"] == to_stop
        # from_seq < to_seq (yön doğru)
        assert first["from_stop_sequence"] < first["to_stop_sequence"]
        # Kalkış saati from_time veya sonrası
        assert first["departure_time"] >= "00:00:00"
        # Süre pozitif
        assert first["duration_seconds"] > 0

    def test_journeys_sorted_by_arrival(self, client, known_route, known_date):
        """Birden fazla sonuç dönerse arrival_time artan sırada gelmeli."""
        from_stop, to_stop, _ = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
            "limit": 10,
        })
        arrivals = [j["arrival_time"] for j in r.json()["direct_journeys"]]
        assert arrivals == sorted(arrivals)

    def test_from_time_filter(self, client, known_route, known_date):
        """from_time sonrasındaki seferler bu saatten önce kalkmamalı."""
        from_stop, to_stop, _ = _discover_stop_pair(client, known_route, known_date)

        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "10:00:00",
            "date": known_date,
            "limit": 10,
        })
        for j in r.json()["direct_journeys"]:
            assert j["departure_time"] >= "10:00:00"

    def test_unknown_stops_returns_empty(self, client, known_date):
        """Olmayan duraklar — 200 + boş cevap (404 değil, query çalışıyor)."""
        r = client.get("/journey", params={
            "from_stop": "YOK_BU_DURAK",
            "to_stop": "YOK_BU_DURAK_DA",
            "from_time": "08:00:00",
            "date": known_date,
        })
        assert r.status_code == 200
        assert r.json()["journey_count"] == 0

    def test_intermediate_count_nonnegative(self, client, known_route, known_date):
        """intermediate_stop_count = to_seq - from_seq - 1, hep ≥ 0 olmalı."""
        from_stop, to_stop, _ = _discover_stop_pair(client, known_route, known_date)
        r = client.get("/journey", params={
            "from_stop": from_stop,
            "to_stop": to_stop,
            "from_time": "00:00:00",
            "date": known_date,
        })
        for j in r.json()["direct_journeys"]:
            assert j["intermediate_stop_count"] >= 0
            assert j["to_stop_sequence"] - j["from_stop_sequence"] - 1 == j["intermediate_stop_count"]

    def test_date_outside_calendar(self, client):
        """Calendar aralığı dışı tarih → boş + note dolu."""
        r = client.get("/journey", params={
            "from_stop": "D1402",
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": "2027-01-01",  # Burulas calendar'ı kapsamayan tarih
        })
        assert r.status_code == 200
        data = r.json()
        assert data["journey_count"] == 0
        # active_service_count 0 ise note dolu olur
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
        """from_stop eksik → 422."""
        r = client.get("/journey", params={
            "to_stop": "D0052",
            "from_time": "08:00:00",
            "date": "2026-04-15",
        })
        assert r.status_code == 422

    def test_limit_respected(self, client, known_date):
        r = client.get("/journey", params={
            "from_stop": "D1402",
            "to_stop": "D0052",
            "from_time": "06:00:00",
            "date": known_date,
            "limit": 2,
        })
        assert r.json()["journey_count"] <= 2
