"""
Trip endpoint için smoke testler.
  - GET /trips/{trip_id}
"""


class TestTripDetail:
    def _sample_trip_id(self, client, known_route) -> str:
        """Bilinen route'tan örnek bir trip_id çek."""
        r = client.get(f"/routes/{known_route['id']}/trips", params={"limit": 1})
        return r.json()["trips"][0]["trip_id"]

    def test_returns_full_detail(self, client, known_route):
        trip_id = self._sample_trip_id(client, known_route)
        r = client.get(f"/trips/{trip_id}")
        assert r.status_code == 200
        data = r.json()

        assert data["trip_id"] == trip_id
        assert data["route_id"] == known_route["id"]
        assert data["route_short_name"] == known_route["short_name"]
        assert data["stop_count"] > 0
        assert data["start_time"]
        assert data["end_time"]

    def test_stops_ordered_by_sequence(self, client, known_route):
        trip_id = self._sample_trip_id(client, known_route)
        r = client.get(f"/trips/{trip_id}")
        seqs = [s["sequence"] for s in r.json()["stops"]]
        assert seqs == sorted(seqs)

    def test_derived_times_match_first_last_stop(self, client, known_route):
        trip_id = self._sample_trip_id(client, known_route)
        data = client.get(f"/trips/{trip_id}").json()
        stops = data["stops"]
        assert data["start_time"] == stops[0]["departure_time"]
        assert data["end_time"] == stops[-1]["arrival_time"]
        assert data["stop_count"] == len(stops)

    def test_start_before_end(self, client, known_route):
        """Bir seferin başlangıç saati bitişinden önce olmalı."""
        trip_id = self._sample_trip_id(client, known_route)
        data = client.get(f"/trips/{trip_id}").json()
        # String karşılaştırma "HH:MM:SS" formatında doğru çalışır
        assert data["start_time"] < data["end_time"]

    def test_unknown_trip_returns_404(self, client):
        r = client.get("/trips/YOK_BU_SEFER")
        assert r.status_code == 404
        assert "bulunamadı" in r.json()["detail"]
