import hmac
import os

from flask import Flask, jsonify, request

from app.reservation_refresh import (
    ReservationRefreshResult,
    refresh_reservation_cache,
)


app = Flask(__name__)


def _load_refresh_token() -> str | None:
    """Charge le jeton de rafraîchissement depuis l'environnement."""

    token = os.environ.get("GOLF_REFRESH_TOKEN", "").strip()
    return token or None


def _extract_bearer_token(header_value: str | None) -> str | None:
    """Extrait un jeton d'un header Authorization Bearer valide."""

    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[len("Bearer ") :].strip()
    return token or None


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "golf_departures_dashboard",
        }
    )


@app.post("/api/reservations/refresh")
def api_refresh_reservations():
    """Déclenche un rafraîchissement authentifié du cache Chronogolf."""

    configured_token = _load_refresh_token()
    if configured_token is None:
        return jsonify(status="error", error="refresh_not_configured"), 503

    request_token = _extract_bearer_token(request.headers.get("Authorization"))
    if request_token is None or not hmac.compare_digest(
        request_token, configured_token
    ):
        return jsonify(status="error", error="unauthorized"), 401

    try:
        result: ReservationRefreshResult = refresh_reservation_cache()
    except Exception:
        app.logger.error("Échec du rafraîchissement Chronogolf.")
        return jsonify(status="error", error="refresh_failed"), 503

    return jsonify(
        status="ok",
        reservations=result.reservations_count,
        updated_at=result.updated_at.isoformat(timespec="seconds"),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
