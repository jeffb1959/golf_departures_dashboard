"""Client Home Assistant pour les prévisions d'Environment Canada."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import socket
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WEATHER_ENV_NAMES = (
    "HOME_ASSISTANT_URL",
    "HOME_ASSISTANT_TOKEN",
    "HA_EC_WEATHER_ENTITY",
)
DEFAULT_HTTP_TIMEOUT = 10.0


class WeatherConfigError(ValueError):
    """Erreur de configuration du client météo Home Assistant."""


class HomeAssistantWeatherError(RuntimeError):
    """Erreur lors de la récupération ou du décodage des prévisions."""


@dataclass(frozen=True)
class HomeAssistantWeatherConfig:
    """Paramètres de connexion à Home Assistant."""

    url: str
    token: str = field(repr=False)
    entity_id: str


@dataclass(frozen=True)
class DailyForecastPeriod:
    """Période normalisée d'une prévision quotidienne."""

    timestamp: datetime
    period: str
    text_summary: str
    temperature: float | None
    temperature_class: str | None
    precipitation_probability: int | None
    icon_code: str | None


@dataclass(frozen=True)
class HourlyForecastPeriod:
    """Période normalisée d'une prévision horaire."""

    timestamp: datetime
    condition: str
    temperature: float | None
    precipitation_probability: int | None
    wind_speed: float | None
    wind_direction: str | None
    uv_index: float | None
    icon_code: str | None


@dataclass(frozen=True)
class EnvironmentCanadaForecast:
    """Prévisions quotidiennes et horaires retournées en un appel."""

    daily: list[DailyForecastPeriod]
    hourly: list[HourlyForecastPeriod]


def load_weather_config(
    environ: Mapping[str, str] | None = None,
) -> HomeAssistantWeatherConfig:
    """Charge la configuration uniquement depuis les variables d'environnement."""

    values = os.environ if environ is None else environ

    def get_value(name: str) -> str:
        value = values.get(name, "")
        return str(value).strip() if value is not None else ""

    loaded = {name: get_value(name) for name in WEATHER_ENV_NAMES}
    missing = [name for name in WEATHER_ENV_NAMES if not loaded[name]]
    if missing:
        raise WeatherConfigError(
            "Variables de configuration météo manquantes: " + ", ".join(missing)
        )

    return HomeAssistantWeatherConfig(
        url=loaded["HOME_ASSISTANT_URL"].rstrip("/"),
        token=loaded["HOME_ASSISTANT_TOKEN"],
        entity_id=loaded["HA_EC_WEATHER_ENTITY"],
    )


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HomeAssistantWeatherError("Timestamp météo absent ou invalide.")
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HomeAssistantWeatherError("Timestamp météo invalide.") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise HomeAssistantWeatherError("Le timestamp météo doit inclure un fuseau horaire.")
    return timestamp


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HomeAssistantWeatherError("Valeur numérique météo invalide.")
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HomeAssistantWeatherError("Valeur numérique météo invalide.")
    return int(value)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _first(item: Mapping[str, Any], *names: str) -> object:
    for name in names:
        if name in item:
            return item[name]
    return None


def _normalize_daily(item: object) -> DailyForecastPeriod:
    if not isinstance(item, Mapping):
        raise HomeAssistantWeatherError("Période quotidienne Home Assistant invalide.")
    return DailyForecastPeriod(
        timestamp=_parse_timestamp(_first(item, "timestamp", "datetime")),
        period=_optional_string(item.get("period")) or "",
        text_summary=_optional_string(_first(item, "text_summary", "summary")) or "",
        temperature=_optional_float(item.get("temperature")),
        temperature_class=_optional_string(item.get("temperature_class")),
        precipitation_probability=_optional_int(
            _first(item, "precip_probability", "precipitation_probability")
        ),
        icon_code=_optional_string(_first(item, "icon_code", "icon")),
    )


def _normalize_hourly(item: object) -> HourlyForecastPeriod:
    if not isinstance(item, Mapping):
        raise HomeAssistantWeatherError("Période horaire Home Assistant invalide.")
    return HourlyForecastPeriod(
        timestamp=_parse_timestamp(_first(item, "timestamp", "datetime")),
        condition=_optional_string(item.get("condition")) or "",
        temperature=_optional_float(item.get("temperature")),
        precipitation_probability=_optional_int(
            _first(item, "precip_probability", "precipitation_probability")
        ),
        wind_speed=_optional_float(item.get("wind_speed")),
        wind_direction=_optional_string(_first(item, "wind_direction", "wind_bearing")),
        uv_index=_optional_float(item.get("uv_index")),
        icon_code=_optional_string(_first(item, "icon_code", "icon")),
    )


def _normalize_response(payload: object, entity_id: str) -> EnvironmentCanadaForecast:
    if not isinstance(payload, Mapping):
        raise HomeAssistantWeatherError("Réponse Home Assistant inattendue.")
    service_response = payload.get("service_response")
    if not isinstance(service_response, Mapping):
        raise HomeAssistantWeatherError("service_response absent de la réponse Home Assistant.")
    entity_response = service_response.get(entity_id)
    if not isinstance(entity_response, Mapping):
        raise HomeAssistantWeatherError("Entité météo absente de la réponse Home Assistant.")
    daily = entity_response.get("daily_forecast")
    hourly = entity_response.get("hourly_forecast")
    if not isinstance(daily, list) or not isinstance(hourly, list):
        raise HomeAssistantWeatherError("Prévisions Home Assistant absentes ou invalides.")
    return EnvironmentCanadaForecast(
        daily=[_normalize_daily(item) for item in daily],
        hourly=[_normalize_hourly(item) for item in hourly],
    )


class HomeAssistantWeatherClient:
    """Récupère les deux granularités de prévisions en un appel REST."""

    def __init__(
        self,
        config: HomeAssistantWeatherConfig,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self._config = config
        self._timeout = timeout

    def get_forecasts(self) -> EnvironmentCanadaForecast:
        url = (
            f"{self._config.url}/api/services/environment_canada/get_forecasts"
            "?return_response"
        )
        body = json.dumps({"entity_id": self._config.entity_id}).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._config.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout) as response:
                status = response.getcode()
                if status is not None and not 200 <= status < 300:
                    raise HomeAssistantWeatherError(
                        f"Home Assistant a retourné le statut HTTP {status}."
                    )
                raw_payload = response.read()
        except HTTPError as exc:
            raise HomeAssistantWeatherError(
                f"Home Assistant a retourné le statut HTTP {exc.code}."
            ) from None
        except (socket.timeout, TimeoutError):
            raise HomeAssistantWeatherError("Délai d'attente Home Assistant dépassé.") from None
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise HomeAssistantWeatherError(
                    "Délai d'attente Home Assistant dépassé."
                ) from None
            raise HomeAssistantWeatherError("Erreur réseau lors de l'appel Home Assistant.") from None
        except OSError:
            raise HomeAssistantWeatherError("Erreur réseau lors de l'appel Home Assistant.") from None

        try:
            payload = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HomeAssistantWeatherError("Réponse JSON Home Assistant invalide.") from None
        return _normalize_response(payload, self._config.entity_id)


def get_forecasts(
    config: HomeAssistantWeatherConfig,
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> EnvironmentCanadaForecast:
    """Raccourci fonctionnel pour récupérer les prévisions."""

    return HomeAssistantWeatherClient(config, timeout=timeout).get_forecasts()
