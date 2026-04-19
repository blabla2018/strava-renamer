import asyncio

from app.config import Settings
from app.db import Database
from app.geocoding import GeoClient
from app.route_analysis import Point


def test_reverse_geocode_prefers_village_name_over_parent_city(tmp_path):
    settings = Settings(webhook_verify_token="token", db_path=tmp_path / "test.db")
    db = Database(settings.db_path)
    db.init()
    client = GeoClient(settings, db)

    async def run():
        async def fake_reverse(params):
            return {
                "addresstype": "village",
                "name": "el Perellonet",
                "address": {
                    "village": "el Perellonet",
                    "suburb": "Pobles del Sud",
                    "city": "València",
                    "county": "Comarca de València",
                    "country": "España",
                },
            }

        client._get_nominatim_reverse = fake_reverse
        place = await client.reverse_geocode(Point(39.3072, -0.29752))
        await client.close()
        return place

    place = asyncio.run(run())

    assert place is not None
    assert place.locality == "el Perellonet"
    assert place.suburb == "Pobles del Sud"
    assert place.raw_rank == 4


def test_reverse_geocode_keeps_city_when_no_more_specific_settlement_exists(tmp_path):
    settings = Settings(webhook_verify_token="token", db_path=tmp_path / "test.db")
    db = Database(settings.db_path)
    db.init()
    client = GeoClient(settings, db)

    async def run():
        async def fake_reverse(params):
            return {
                "addresstype": "city",
                "name": "València",
                "address": {
                    "city": "València",
                    "suburb": "l'Olivereta",
                    "county": "Comarca de València",
                    "country": "España",
                },
            }

        client._get_nominatim_reverse = fake_reverse
        place = await client.reverse_geocode(Point(39.47, -0.39))
        await client.close()
        return place

    place = asyncio.run(run())

    assert place is not None
    assert place.locality == "València"
    assert place.suburb == "l'Olivereta"


def test_reverse_geocode_does_not_promote_suburb_over_city(tmp_path):
    settings = Settings(webhook_verify_token="token", db_path=tmp_path / "test.db")
    db = Database(settings.db_path)
    db.init()
    client = GeoClient(settings, db)

    async def run():
        async def fake_reverse(params):
            return {
                "addresstype": "suburb",
                "name": "Nou Moles",
                "address": {
                    "suburb": "Nou Moles",
                    "city": "València",
                    "county": "Comarca de València",
                    "country": "España",
                },
            }

        client._get_nominatim_reverse = fake_reverse
        place = await client.reverse_geocode(Point(39.47, -0.39))
        await client.close()
        return place

    place = asyncio.run(run())

    assert place is not None
    assert place.locality == "València"
    assert place.suburb == "Nou Moles"


def test_reverse_geocode_prefers_parent_town_over_hamlet(tmp_path):
    db = Database(tmp_path / "service.db")
    db.init()
    settings = Settings(webhook_verify_token="token", geo_cache_only=False)
    client = GeoClient(settings, db)

    payload = {
        "name": "Masia del Raco",
        "addresstype": "hamlet",
        "address": {
            "hamlet": "Masia del Raco",
            "town": "Cullera",
            "country": "España",
        },
    }
    params = {
        "format": "jsonv2",
        "lat": 39.15538,
        "lon": -0.25392,
        "zoom": 14,
        "addressdetails": 1,
    }
    db.put_geo_cache(client._cache_key("nominatim-reverse", params), "nominatim", payload)

    place = asyncio.run(client.reverse_geocode(Point(lat=39.15538, lon=-0.25392)))
    asyncio.run(client.close())

    assert place is not None
    assert place.locality == "Cullera"
