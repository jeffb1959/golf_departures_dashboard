import hmac
import os

from flask import Flask, jsonify, request, send_file

from app.display_artifact import DEFAULT_DISPLAY_OUTPUT_DIR, get_display_artifact_path
from app.display_targets import get_display_target
from app.dashboard_refresh import DashboardRefreshError, refresh_dashboard

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


@app.post("/api/dashboard/refresh")
def api_refresh_dashboard():
    """Déclenche un rafraîchissement complet du dashboard."""

    configured_token = _load_refresh_token()
    if configured_token is None:
        return jsonify(status="error", error="refresh_not_configured"), 503

    request_token = _extract_bearer_token(request.headers.get("Authorization"))
    if request_token is None or not hmac.compare_digest(request_token, configured_token):
        return jsonify(status="error", error="unauthorized"), 401

    try:
        result = refresh_dashboard()
    except DashboardRefreshError as exc:
        if exc.stage == "reservations":
            app.logger.error("Échec du rafraîchissement complet du dashboard: phase réservations.")
            return jsonify(
                status="error",
                error="dashboard_reservations_refresh_failed",
            ), 503

        app.logger.error("Échec du rafraîchissement complet du dashboard: phase affichage.")
        return jsonify(
            status="error",
            error="dashboard_display_refresh_failed",
        ), 503

    return jsonify(
        status="ok",
        reservations={
            "count": result.reservations_count,
            "updated_at": result.reservations_updated_at.isoformat(timespec="seconds"),
        },
        display={
            "profile": result.display_profile,
            "payload_size": result.display_payload_size,
            "departures_count": result.display_departures_count,
            "generated_at": result.display_generated_at.isoformat(timespec="seconds"),
        },
    )


@app.get("/api/display/artifact")
def api_display_artifact():
    """Expose l'artefact déjà généré pour le profil courant."""

    try:
        target = get_display_target()
    except Exception:
        app.logger.error("Profil d'affichage invalide pour la route /api/display/artifact.")
        return jsonify(
            status="error",
            error="display_not_configured",
        ), 503

    artifact_path = get_display_artifact_path(target, output_dir=DEFAULT_DISPLAY_OUTPUT_DIR)
    if not artifact_path.exists() or not artifact_path.is_file():
        return jsonify(
            status="error",
            error="display_artifact_not_found",
        ), 404

    response = send_file(
        artifact_path,
        mimetype=target.mime_type,
        download_name=artifact_path.name,
        as_attachment=False,
        etag=False,
    )
    response.headers["X-Display-Profile"] = target.name
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
