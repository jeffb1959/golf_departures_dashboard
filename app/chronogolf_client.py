"""Client IMAP pour récupérer les confirmations Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Mapping
import imaplib
import os
import socket
import ssl

from app import reservation_parser


CONFIRMATION_SUBJECTS = (
    "confirmation de réservation",
    "tee time booking confirmation",
)
SEARCH_WINDOW_DAYS = 7
IMAP_MONTHS_EN = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
IMAP_ENV_NAMES = (
    "VIDEOTRON_IMAP_HOST",
    "VIDEOTRON_IMAP_PORT",
    "VIDEOTRON_IMAP_USER",
    "VIDEOTRON_IMAP_PASSWORD",
)


class ImapConfigError(ValueError):
    """Erreur de configuration IMAP."""


class ChronogolfIMAPError(RuntimeError):
    """Erreur réseau ou serveur IMAP pour Chronogolf."""


ImapConnection = object


@dataclass(frozen=True)
class ImapConfig:
    """Paramètres de connexion à la boîte IMAP."""

    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class ChronogolfFetchResult:
    """Résultat de la récupération IMAP avec métriques."""

    search_since: date
    messages_examined: int
    confirmations_found: int
    confirmations_ignored: int
    reservations: list[reservation_parser.GolfReservation]


def load_imap_config(environ: Mapping[str, str] | None = None) -> ImapConfig:
    """Charge la configuration uniquement depuis un mapping d'environnement."""

    values = os.environ if environ is None else environ

    def get_value(name: str) -> str:
        value = values.get(name, "")
        return str(value).strip() if value is not None else ""

    loaded = {name: get_value(name) for name in IMAP_ENV_NAMES}
    missing = [name for name in IMAP_ENV_NAMES if not loaded[name]]
    if missing:
        raise ImapConfigError(
            "Variables de configuration IMAP manquantes: " + ", ".join(missing)
        )

    try:
        port = int(loaded["VIDEOTRON_IMAP_PORT"])
    except ValueError as exc:
        raise ImapConfigError("VIDEOTRON_IMAP_PORT doit être un entier.") from exc
    if port <= 0:
        raise ImapConfigError("VIDEOTRON_IMAP_PORT doit être > 0.")

    return ImapConfig(
        host=loaded["VIDEOTRON_IMAP_HOST"],
        port=port,
        user=loaded["VIDEOTRON_IMAP_USER"],
        password=loaded["VIDEOTRON_IMAP_PASSWORD"],
    )


def _search_start_date(reference: datetime | None = None) -> date:
    return (reference or datetime.now()).date() - timedelta(days=SEARCH_WINDOW_DAYS)


def format_imap_since_date(reference: datetime | None = None) -> str:
    """Retourne la date IMAP au format ``DD-MMM-YYYY``."""

    start_date = _search_start_date(reference)
    month = IMAP_MONTHS_EN[start_date.month - 1]
    return f"{start_date.day:02d}-{month}-{start_date.year}"


def decode_mime_subject(raw_subject: str | None) -> str:
    """Décode un sujet MIME potentiellement encodé."""

    if not raw_subject:
        return ""
    fragments: list[str] = []
    for value, charset in decode_header(raw_subject):
        if isinstance(value, bytes):
            fragments.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            fragments.append(value)
    return "".join(fragments).strip()


def _normalize_subject(subject: str) -> str:
    return " ".join(subject.casefold().split())


def is_confirmation_subject(raw_subject: str | None) -> bool:
    """Indique si le sujet correspond à une confirmation de réservation."""

    normalized = _normalize_subject(decode_mime_subject(raw_subject))
    normalized_targets = (_normalize_subject(subject) for subject in CONFIRMATION_SUBJECTS)
    return any(
        (normalized == target) or (f" {target} " in f" {normalized} ")
        for target in normalized_targets
    )


def _extract_headers(message_bytes: bytes) -> tuple[str, datetime | None]:
    message = BytesParser(policy=default_policy).parsebytes(message_bytes)
    subject = message["Subject"]
    date_header = message["Date"]
    received_at = (
        parsedate_to_datetime(str(date_header)) if date_header else None
    )
    return decode_mime_subject(str(subject) if subject else ""), received_at


def _iter_payload(fetch_payload: object) -> Iterable[bytes]:
    if not isinstance(fetch_payload, (tuple, list)):
        return
    for item in fetch_payload:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            yield item[1]


def _default_imap_factory(host: str, port: int) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(
        host,
        port,
        ssl_context=ssl.create_default_context(),
    )


class ChronogolfClient:
    """Client IMAP dédié aux réservations Chronogolf à venir."""

    def __init__(
        self,
        config: ImapConfig,
        *,
        imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
    ) -> None:
        self._config = config
        self._imap_factory = imap_factory

    def get_upcoming_reservations_with_report(
        self,
        reference: datetime | None = None,
        today: date | None = None,
    ) -> ChronogolfFetchResult:
        return _get_reservations(
            config=self._config,
            reference=reference,
            today=today,
            imap_factory=self._imap_factory,
        )

    def get_upcoming_reservations(
        self,
        reference: datetime | None = None,
        today: date | None = None,
    ) -> list[reservation_parser.GolfReservation]:
        return self.get_upcoming_reservations_with_report(
            reference=reference,
            today=today,
        ).reservations


def get_upcoming_reservations_with_report(
    config: ImapConfig,
    *,
    reference: datetime | None = None,
    today: date | None = None,
    imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
) -> ChronogolfFetchResult:
    return _get_reservations(
        config=config,
        reference=reference,
        today=today,
        imap_factory=imap_factory,
    )


def get_upcoming_reservations(
    config: ImapConfig,
    *,
    reference: datetime | None = None,
    today: date | None = None,
    imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
) -> list[reservation_parser.GolfReservation]:
    return get_upcoming_reservations_with_report(
        config=config,
        reference=reference,
        today=today,
        imap_factory=imap_factory,
    ).reservations


def _get_reservations(
    *,
    config: ImapConfig,
    reference: datetime | None,
    today: date | None,
    imap_factory: Callable[..., ImapConnection],
) -> ChronogolfFetchResult:
    search_date = _search_start_date(reference)
    messages_examined = 0
    confirmations_found = 0
    confirmations_ignored = 0
    reservations: list[reservation_parser.GolfReservation] = []
    imap = None

    try:
        try:
            imap = imap_factory(config.host, config.port)
        except TypeError:
            imap = imap_factory(config)
        imap.login(config.user, config.password)

        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise ChronogolfIMAPError("Impossible de sélectionner INBOX en lecture seule.")

        status, raw_ids = imap.search(None, "SINCE", format_imap_since_date(reference))
        if status != "OK":
            raise ChronogolfIMAPError("La recherche IMAP a échoué.")
        message_ids = raw_ids[0].decode("utf-8").split() if raw_ids and raw_ids[0] else []

        for message_id in message_ids:
            status, header_data = imap.fetch(
                message_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])"
            )
            if status != "OK" or not header_data:
                continue
            header_payload = b"".join(_iter_payload(header_data))
            if not header_payload:
                continue

            subject, received_at = _extract_headers(header_payload)
            messages_examined += 1
            if not is_confirmation_subject(subject):
                continue

            confirmations_found += 1
            status, body_data = imap.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not body_data:
                confirmations_ignored += 1
                continue
            body_payload = b"".join(_iter_payload(body_data))
            if not body_payload:
                confirmations_ignored += 1
                continue

            try:
                body_text = reservation_parser.extract_confirmation_body_text(body_payload)
                reservations.append(
                    reservation_parser.parse_confirmation_reservation(
                        body_text,
                        received_at=received_at,
                    )
                )
            except reservation_parser.ReservationParseError:
                confirmations_ignored += 1

    except ChronogolfIMAPError:
        raise
    except ssl.SSLError as exc:
        raise ChronogolfIMAPError("Erreur SSL IMAP.") from exc
    except imaplib.IMAP4.error as exc:
        raise ChronogolfIMAPError("Échec d’authentification IMAP.") from exc
    except (socket.gaierror, OSError) as exc:
        raise ChronogolfIMAPError("Erreur réseau IMAP.") from exc
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass

    upcoming = reservation_parser.filter_upcoming_reservations(
        reservations, today=today or date.today()
    )
    deduplicated = reservation_parser.deduplicate_reservations(upcoming)
    sorted_reservations = reservation_parser.sort_reservations(deduplicated)
    return ChronogolfFetchResult(
        search_since=search_date,
        messages_examined=messages_examined,
        confirmations_found=confirmations_found,
        confirmations_ignored=confirmations_ignored,
        reservations=sorted_reservations,
    )
