"""Tests unitaires du client météo, sans connexion Home Assistant réelle."""

from __future__ import annotations

import json
import os
import socket
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app import weather_client


FAKE_TOKEN = "jeton-home-assistant-strictement-fictif"
ENTITY_ID = "weather.exemple_previsions"


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self.payload


def forecast_payload() -> dict[str, object]:
    return {
        "service_response": {
            ENTITY_ID: {
                "daily_forecast": [
                    {
                        "datetime": "2026-08-29T00:00:00-04:00",
                        "period": "Samedi",
                        "summary": "Ensoleillé",
                        "temperature": None,
                        "temperature_class": "high",
                        "precip_probability": 0,
                        "icon": "00",
                    },
                    {
                        "timestamp": "2026-08-30T04:00:00Z",
                        "period": "Dimanche",
                        "text_summary": "Nuageux",
                    },
                ],
                "hourly_forecast": [
                    {
                        "datetime": "2026-08-29T09:00:00-04:00",
                        "condition": "sunny",
                        "temperature": 21,
                        "precip_probability": 90,
                        "wind_speed": 12,
                        "wind_bearing": "NE",
                        "uv_index": 4,
                        "icon": "01",
                    }
                ],
            }
        }
    }


class WeatherClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = weather_client.HomeAssistantWeatherConfig(
            url="http://homeassistant.example.test:8123",
            token=FAKE_TOKEN,
            entity_id=ENTITY_ID,
        )

    def test_load_config_and_remove_trailing_slashes(self) -> None:
        config = weather_client.load_weather_config(
            {
                "HOME_ASSISTANT_URL": " http://homeassistant.example.test:8123/// ",
                "HOME_ASSISTANT_TOKEN": FAKE_TOKEN,
                "HA_EC_WEATHER_ENTITY": ENTITY_ID,
            }
        )
        self.assertEqual(config.url, "http://homeassistant.example.test:8123")
        self.assertEqual(config.token, FAKE_TOKEN)
        self.assertEqual(config.entity_id, ENTITY_ID)
        self.assertNotIn(FAKE_TOKEN, repr(config))

    def test_load_config_uses_environment_by_default(self) -> None:
        values = {
            "HOME_ASSISTANT_URL": "http://ha.environnement.test",
            "HOME_ASSISTANT_TOKEN": FAKE_TOKEN,
            "HA_EC_WEATHER_ENTITY": ENTITY_ID,
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(weather_client.load_weather_config().url, values["HOME_ASSISTANT_URL"])

    def test_missing_config_is_clean_and_does_not_expose_token(self) -> None:
        with self.assertRaises(weather_client.WeatherConfigError) as context:
            weather_client.load_weather_config(
                {"HOME_ASSISTANT_URL": "", "HOME_ASSISTANT_TOKEN": FAKE_TOKEN}
            )
        message = str(context.exception)
        self.assertIn("HOME_ASSISTANT_URL", message)
        self.assertIn("HA_EC_WEATHER_ENTITY", message)
        self.assertNotIn(FAKE_TOKEN, message)

    @patch("app.weather_client.urlopen")
    def test_request_and_both_forecast_types_are_normalized(self, mocked_open) -> None:
        mocked_open.return_value = FakeResponse(json.dumps(forecast_payload()).encode())
        result = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts()

        request = mocked_open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://homeassistant.example.test:8123/api/services/"
            "environment_canada/get_forecasts?return_response",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {FAKE_TOKEN}")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"entity_id": ENTITY_ID})
        self.assertEqual(mocked_open.call_args.kwargs["timeout"], 10.0)

        self.assertEqual(len(result.daily), 2)
        self.assertEqual(len(result.hourly), 1)
        self.assertIsNone(result.daily[0].temperature)
        self.assertEqual(result.daily[0].precipitation_probability, 0)
        self.assertEqual(result.daily[0].text_summary, "Ensoleillé")
        self.assertEqual(result.hourly[0].temperature, 21.0)
        self.assertEqual(result.hourly[0].precipitation_probability, 90)
        self.assertEqual(result.hourly[0].wind_direction, "NE")
        self.assertIsNotNone(result.daily[0].timestamp.utcoffset())
        self.assertEqual(result.daily[1].timestamp.utcoffset().total_seconds(), 0)

    @patch("app.weather_client.urlopen")
    def test_absent_optional_fields_become_none(self, mocked_open) -> None:
        mocked_open.return_value = FakeResponse(json.dumps(forecast_payload()).encode())
        period = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts().daily[1]
        self.assertIsNone(period.temperature)
        self.assertIsNone(period.temperature_class)
        self.assertIsNone(period.precipitation_probability)
        self.assertIsNone(period.icon_code)

    @patch("app.weather_client.urlopen")
    def test_daily_precipitation_probability_prioritizes_precip_probability_field(self, mocked_open) -> None:
        mocked_open.return_value = FakeResponse(json.dumps(forecast_payload()).encode())
        result = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts()
        self.assertEqual(result.daily[0].precipitation_probability, 0)

    @patch("app.weather_client.urlopen")
    def test_hourly_precipitation_probability_prioritizes_precip_probability_field(self, mocked_open) -> None:
        mocked_open.return_value = FakeResponse(json.dumps(forecast_payload()).encode())
        result = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts()
        self.assertEqual(result.hourly[0].precipitation_probability, 90)

    @patch("app.weather_client.urlopen")
    def test_precipitation_probability_alias_is_still_accepted(self, mocked_open) -> None:
        payload = forecast_payload()
        payload["service_response"][ENTITY_ID]["daily_forecast"][0][
            "precipitation_probability"
        ] = 11
        payload["service_response"][ENTITY_ID]["daily_forecast"][0].pop(
            "precip_probability", None
        )
        payload["service_response"][ENTITY_ID]["hourly_forecast"][0][
            "precipitation_probability"
        ] = 22
        payload["service_response"][ENTITY_ID]["hourly_forecast"][0].pop(
            "precip_probability", None
        )
        mocked_open.return_value = FakeResponse(json.dumps(payload).encode())
        result = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts()
        self.assertEqual(result.daily[0].precipitation_probability, 11)
        self.assertEqual(result.hourly[0].precipitation_probability, 22)

    @patch("app.weather_client.urlopen")
    def test_missing_precipitation_probability_becomes_none(self, mocked_open) -> None:
        payload = forecast_payload()
        payload["service_response"][ENTITY_ID]["daily_forecast"][0].pop(
            "precip_probability", None
        )
        payload["service_response"][ENTITY_ID]["daily_forecast"][0].pop(
            "precipitation_probability", None
        )
        payload["service_response"][ENTITY_ID]["hourly_forecast"][0].pop(
            "precip_probability", None
        )
        payload["service_response"][ENTITY_ID]["hourly_forecast"][0].pop(
            "precipitation_probability", None
        )
        mocked_open.return_value = FakeResponse(json.dumps(payload).encode())
        result = weather_client.HomeAssistantWeatherClient(self.config).get_forecasts()
        self.assertIsNone(result.daily[0].precipitation_probability)
        self.assertIsNone(result.hourly[0].precipitation_probability)

    def test_http_error_is_clean(self) -> None:
        error = HTTPError("http://example.test", 500, FAKE_TOKEN, {}, None)
        with patch("app.weather_client.urlopen", side_effect=error):
            with self.assertRaises(weather_client.HomeAssistantWeatherError) as context:
                weather_client.get_forecasts(self.config)
        self.assertIn("500", str(context.exception))
        self.assertNotIn(FAKE_TOKEN, str(context.exception))

    def test_non_2xx_response_is_rejected(self) -> None:
        with patch("app.weather_client.urlopen", return_value=FakeResponse(b"{}", 503)):
            with self.assertRaisesRegex(weather_client.HomeAssistantWeatherError, "503"):
                weather_client.get_forecasts(self.config)

    def test_network_error_is_clean(self) -> None:
        with patch("app.weather_client.urlopen", side_effect=URLError(FAKE_TOKEN)):
            with self.assertRaises(weather_client.HomeAssistantWeatherError) as context:
                weather_client.get_forecasts(self.config)
        self.assertIn("réseau", str(context.exception))
        self.assertNotIn(FAKE_TOKEN, str(context.exception))

    def test_timeout_is_clean(self) -> None:
        with patch("app.weather_client.urlopen", side_effect=socket.timeout(FAKE_TOKEN)):
            with self.assertRaises(weather_client.HomeAssistantWeatherError) as context:
                weather_client.get_forecasts(self.config)
        self.assertIn("attente", str(context.exception))
        self.assertNotIn(FAKE_TOKEN, str(context.exception))

    def test_timeout_wrapped_by_urlerror_is_clean(self) -> None:
        error = URLError(socket.timeout(FAKE_TOKEN))
        with patch("app.weather_client.urlopen", side_effect=error):
            with self.assertRaises(weather_client.HomeAssistantWeatherError) as context:
                weather_client.get_forecasts(self.config)
        self.assertIn("attente", str(context.exception))
        self.assertNotIn(FAKE_TOKEN, str(context.exception))

    def test_invalid_json_is_rejected(self) -> None:
        with patch("app.weather_client.urlopen", return_value=FakeResponse(b"not json")):
            with self.assertRaisesRegex(weather_client.HomeAssistantWeatherError, "JSON"):
                weather_client.get_forecasts(self.config)

    def test_missing_service_response_is_rejected(self) -> None:
        with patch("app.weather_client.urlopen", return_value=FakeResponse(b"{}")):
            with self.assertRaisesRegex(weather_client.HomeAssistantWeatherError, "service_response"):
                weather_client.get_forecasts(self.config)

    def test_missing_entity_is_rejected(self) -> None:
        raw = json.dumps({"service_response": {}}).encode()
        with patch("app.weather_client.urlopen", return_value=FakeResponse(raw)):
            with self.assertRaisesRegex(weather_client.HomeAssistantWeatherError, "Entité"):
                weather_client.get_forecasts(self.config)


if __name__ == "__main__":
    unittest.main()
