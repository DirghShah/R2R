"""Google failing wholesale must not mean no pins.

On 10 October the Places key started returning 403 for every call — billing,
enablement or a key restriction, the status alone doesn't say. The pipeline
logged a warning per place and saved each one unmapped, so the only visible
symptom was pins quietly not appearing, for four days. Nominatim was sitting
right there, already implemented, and was never asked.
"""

from types import SimpleNamespace

from worker import geocode


def _place(name="Uncle Zhou Restaurant", city="Plano"):
    return SimpleNamespace(name=name, city=city, country="US", category=None)


def _blank(place):
    return geocode.GeocodeResult(name=place.name, city=place.city, country="US")


def _pinned(place, lat=33.02, lng=-96.69):
    return geocode.GeocodeResult(name=place.name, city=place.city, country="US",
                                 lat=lat, lng=lng)


def test_falls_back_to_nominatim_when_google_returns_no_pin(monkeypatch):
    monkeypatch.setattr(geocode.settings, "geocoder", "google")
    monkeypatch.setattr(geocode.settings, "google_places_api_key", "k")
    monkeypatch.setattr(geocode, "_google", lambda p, hint=None: _blank(p))

    asked = []

    def fake_nominatim(place):
        asked.append(place.name)
        return _pinned(place)

    monkeypatch.setattr(geocode, "_nominatim", fake_nominatim)

    out = geocode.geocode(_place())
    assert asked == ["Uncle Zhou Restaurant"], "Nominatim was never consulted"
    assert (out.lat, out.lng) == (33.02, -96.69)


def test_google_result_wins_when_it_has_coordinates(monkeypatch):
    """The fallback must not cost the ratings and photos on the happy path."""
    monkeypatch.setattr(geocode.settings, "geocoder", "google")
    monkeypatch.setattr(geocode.settings, "google_places_api_key", "k")
    monkeypatch.setattr(geocode, "_google", lambda p, hint=None: _pinned(p, 1.0, 2.0))
    monkeypatch.setattr(geocode, "_nominatim",
                        lambda p: pytest_fail("Nominatim called despite a Google pin"))

    out = geocode.geocode(_place())
    assert (out.lat, out.lng) == (1.0, 2.0)


def test_still_unpinned_when_both_fail(monkeypatch):
    """Nominatim is a fallback, not a guarantee — an unknown name stays unmapped."""
    monkeypatch.setattr(geocode.settings, "geocoder", "google")
    monkeypatch.setattr(geocode.settings, "google_places_api_key", "k")
    monkeypatch.setattr(geocode, "_google", lambda p, hint=None: _blank(p))
    monkeypatch.setattr(geocode, "_nominatim", _blank)

    out = geocode.geocode(_place())
    assert out.lat is None
    assert out.name == "Uncle Zhou Restaurant"


def pytest_fail(msg):
    raise AssertionError(msg)
