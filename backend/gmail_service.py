import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build


logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]
TOKEN_PATH = Path(__file__).resolve().parent / "config" / "gmail_token.json"
STATE_PATH = Path(__file__).resolve().parent / "config" / "gmail_oauth_state.json"
CLIENT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "google_client_secret.json"

AIRLINE_QUERY = (
    '(flight OR airline OR boarding OR delayed OR cancelled OR cancellation OR itinerary) '
    'newer_than:180d'
)


@dataclass
class ExtractedClaim:
    airline: str
    flight_number: str
    flight_date: str
    delay_reason: str
    delay_minutes: int
    departure_airport: str
    arrival_airport: str
    scheduled_departure: str
    actual_departure: str
    booking_reference: str
    ticket_number: str
    email_subject: str
    email_from: str
    snippet: str


class GmailConfigurationError(RuntimeError):
    pass


def _load_client_config() -> Dict[str, Any]:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8001/api/gmail/callback")

    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }

    if CLIENT_CONFIG_PATH.exists():
        return json.loads(CLIENT_CONFIG_PATH.read_text())

    raise GmailConfigurationError(
        "Google OAuth credentials are missing. Set GOOGLE_OAUTH_CLIENT_ID and "
        "GOOGLE_OAUTH_CLIENT_SECRET in backend/.env or add backend/config/google_client_secret.json."
    )


def _get_redirect_uri() -> str:
    return os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8001/api/gmail/callback")


def _get_frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:8000")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def get_authorization_url() -> str:
    flow = Flow.from_client_config(
        _load_client_config(),
        scopes=SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = _get_redirect_uri()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _ensure_parent(STATE_PATH)
    STATE_PATH.write_text(json.dumps({
        "state": state,
        "code_verifier": flow.code_verifier,
    }))
    return auth_url


def exchange_code_for_token(code: str, state: str) -> None:
    saved_payload = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    saved_state = saved_payload.get("state")
    code_verifier = saved_payload.get("code_verifier")
    if not saved_state or state != saved_state:
        raise GmailConfigurationError("Invalid OAuth state. Please reconnect Gmail.")

    flow = Flow.from_client_config(_load_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = _get_redirect_uri()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    credentials = flow.credentials
    _persist_credentials(credentials)


def _persist_credentials(credentials: Credentials) -> None:
    _ensure_parent(TOKEN_PATH)
    TOKEN_PATH.write_text(credentials.to_json())


def load_credentials() -> Optional[Credentials]:
    if not TOKEN_PATH.exists():
        return None

    credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials.expired and credentials.refresh_token:
        logger.info("[Gmail] Refreshing expired Gmail token")
        credentials.refresh(Request())
        _persist_credentials(credentials)
    return credentials


def disconnect_gmail() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


def gmail_status() -> Dict[str, Any]:
    credentials = load_credentials()
    return {
        "connected": credentials is not None and credentials.valid,
        "configured": _gmail_configured(),
    }


def _gmail_configured() -> bool:
    return bool(
        (os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"))
        or CLIENT_CONFIG_PATH.exists()
    )


def _gmail_service():
    credentials = load_credentials()
    if not credentials or not credentials.valid:
        raise GmailConfigurationError("Gmail is not connected.")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def scan_inbox_for_claims(max_results: int = 10) -> Dict[str, Any]:
    service = _gmail_service()
    logger.info("[Gmail] Searching inbox for recent flight-related emails")
    response = (
        service.users()
        .messages()
        .list(userId="me", q=AIRLINE_QUERY, maxResults=max_results)
        .execute()
    )
    messages = response.get("messages", [])
    logger.info("[Gmail] Found %d candidate email(s)", len(messages))

    extracted: List[ExtractedClaim] = []
    for message_ref in messages:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_ref["id"], format="raw")
            .execute()
        )
        parsed = _parse_email_payload(message)
        claim = _extract_claim_from_email(parsed)
        if claim:
            extracted.append(claim)

    if not extracted:
        return {
            "status": "no_matches",
            "message": "No flight disruption emails with enough detail were found.",
            "emails_scanned": len(messages),
        }

    claim = extracted[0]
    return {
        "status": "match_found",
        "message": f"Found a likely flight disruption email for {claim.flight_number}.",
        "claim_data": {
            "flight_number": claim.flight_number,
            "flight_date": claim.flight_date,
            "delay_reason": claim.delay_reason,
            "delay_minutes": claim.delay_minutes,
            "jurisdiction": "EU",
        },
        "extracted_email_data": {
            "airline": claim.airline,
            "departure_airport": claim.departure_airport,
            "arrival_airport": claim.arrival_airport,
            "scheduled_departure": claim.scheduled_departure,
            "actual_departure": claim.actual_departure,
            "booking_reference": claim.booking_reference,
            "ticket_number": claim.ticket_number,
        },
        "source_email": {
            "subject": claim.email_subject,
            "from": claim.email_from,
            "snippet": claim.snippet,
        },
        "emails_scanned": len(messages),
    }


def _parse_email_payload(message: Dict[str, Any]) -> Dict[str, str]:
    raw_data = base64.urlsafe_b64decode(message["raw"].encode("utf-8"))
    email_message = message_from_bytes(raw_data)
    subject = email_message.get("Subject", "")
    sender = email_message.get("From", "")
    body = _extract_body(email_message)
    return {
        "subject": subject,
        "from": sender,
        "body": body,
        "snippet": message.get("snippet", ""),
    }


def _extract_body(email_message) -> str:
    if email_message.is_multipart():
        parts = []
        for part in email_message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                parts.append(payload.decode(charset, errors="ignore"))
        return "\n".join(parts)

    payload = email_message.get_payload(decode=True) or b""
    charset = email_message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="ignore")


def _extract_claim_from_email(email_data: Dict[str, str]) -> Optional[ExtractedClaim]:
    combined = f"{email_data['subject']}\n{email_data['body']}\n{email_data['snippet']}"
    flight_number = _extract_flight_number(combined)
    flight_date = _extract_date(combined)
    delay_minutes = _extract_delay_minutes(combined)
    delay_reason = _extract_delay_reason(combined)

    if not (flight_number and flight_date and delay_minutes):
        return None

    return ExtractedClaim(
        airline=_extract_field(text=combined, label_patterns=[r"Airline"], default=_infer_airline(email_data["subject"], email_data["from"])),
        flight_number=flight_number,
        flight_date=flight_date,
        delay_reason=delay_reason or "Flight disruption detected from Gmail message",
        delay_minutes=delay_minutes,
        departure_airport=_extract_airport(text=combined, direction="departure"),
        arrival_airport=_extract_airport(text=combined, direction="arrival"),
        scheduled_departure=_extract_field(text=combined, label_patterns=[r"Scheduled Departure", r"Original Departure"], default="Unknown"),
        actual_departure=_extract_field(text=combined, label_patterns=[r"Actual Departure", r"Updated Departure"], default="Unknown"),
        booking_reference=_extract_field(text=combined, label_patterns=[r"Booking Reference", r"PNR"], default="Not provided"),
        ticket_number=_extract_field(text=combined, label_patterns=[r"Ticket Number"], default="Not provided"),
        email_subject=email_data["subject"],
        email_from=email_data["from"],
        snippet=email_data["snippet"],
    )


def build_formal_claim_letter(
    analysis: Dict[str, Any],
    claim_data: Dict[str, Any],
    extracted_email_data: Dict[str, str],
    contact_email: str,
) -> str:
    airline = extracted_email_data.get("airline") or "Airline"
    flight_number = claim_data.get("flight_number", "Unknown")
    flight_date = claim_data.get("flight_date", "Unknown")
    departure_airport = extracted_email_data.get("departure_airport", "Departure airport")
    arrival_airport = extracted_email_data.get("arrival_airport", "Arrival airport")
    scheduled_departure = extracted_email_data.get("scheduled_departure", "Unknown")
    actual_departure = extracted_email_data.get("actual_departure", "Unknown")
    booking_reference = extracted_email_data.get("booking_reference", "Not provided")
    ticket_number = extracted_email_data.get("ticket_number", "Not provided")
    delay_reason = claim_data.get("delay_reason", "Operational issues")
    delay_minutes = claim_data.get("delay_minutes", 0)
    compensation = analysis.get("compensation_eur", 0)

    return f"""Subject: EU261/2004 Compensation Claim - {airline} Flight {flight_number} | {departure_airport} -> {arrival_airport} | {flight_date}

To Whom It May Concern,
{airline} Customer Relations Department,

I am writing to formally request compensation under EC Regulation No. 261/2004 for a significant flight delay I experienced on my recent flight.

-------------------------------------------------------------------
PASSENGER DETAILS
-------------------------------------------------------------------
Full Name         : [YOUR FULL NAME]
Booking Reference : {booking_reference}
Ticket Number     : {ticket_number}
Contact Email     : {contact_email}
Contact Phone     : [YOUR PHONE NUMBER]

-------------------------------------------------------------------
FLIGHT DETAILS
-------------------------------------------------------------------
Airline              : {airline}
Flight Number        : {flight_number}
Departure Airport    : {departure_airport}
Arrival Airport      : {arrival_airport}
Scheduled Departure  : {scheduled_departure}
Actual Departure     : {actual_departure}
Total Delay          : Approximately {delay_minutes} minutes
Reason Given by Airline : {delay_reason}

-------------------------------------------------------------------
BASIS FOR CLAIM
-------------------------------------------------------------------
Under EC Regulation No. 261/2004, I am entitled to compensation
on the following grounds:

1. APPLICABILITY: The operating carrier and route fall within the
   scope of EU261 based on the information provided in the booking
   and disruption email.

2. DELAY THRESHOLD MET: The flight disruption exceeded the 3-hour
   threshold used for compensation eligibility analysis.

3. COMPENSATION AMOUNT DUE: Per {analysis.get("regulation_reference", "EU261 Article 7")},
   I am requesting EUR {compensation} per passenger.

4. EXTRAORDINARY CIRCUMSTANCES: The stated reason "{delay_reason}"
   does not appear to exempt the airline from compensation under
   the current claim analysis.

-------------------------------------------------------------------
COMPENSATION REQUESTED
-------------------------------------------------------------------
Monetary Compensation     : EUR {compensation}.00 (per passenger)
Payment Method Preference : Bank Transfer / [Your Preference]

-------------------------------------------------------------------
DOCUMENTS ENCLOSED (attach copies)
-------------------------------------------------------------------
- Booking confirmation / e-ticket
- Boarding pass(es)
- Delay or cancellation notification email
- Any written communication received from the airline

-------------------------------------------------------------------
RESPONSE DEADLINE
-------------------------------------------------------------------
I kindly request a written response and resolution within 14 days
of receiving this letter. Should I not receive a satisfactory
response within this timeframe, I reserve the right to escalate
this matter to the relevant enforcement body or dispute resolution
channel.

Yours sincerely,

[YOUR FULL NAME]
[YOUR ADDRESS]
[CITY, COUNTRY, ZIP CODE]
{contact_email}
[YOUR PHONE NUMBER]
[DATE]""".strip()


def _extract_flight_number(text: str) -> Optional[str]:
    labeled = _extract_field(text, [r"Flight Number"], default="")
    if labeled:
        cleaned = re.sub(r"[^A-Z0-9 ]", "", labeled.upper()).strip()
        return cleaned.replace(" ", "")

    matches = re.findall(r"\b([A-Z]{2,3}\s?\d{2,4})\b", text.upper())
    for match in matches:
        normalized = match.replace(" ", "")
        if normalized.startswith("EU"):
            continue
        return normalized
    return None


def _extract_date(text: str) -> Optional[str]:
    patterns = [
        r"\b(20\d{2}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}/\d{1,2}/20\d{2})\b",
        r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+20\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def _extract_delay_minutes(text: str) -> Optional[int]:
    labeled_match = re.search(r"Total Delay\s*:\s*(.+)", text, re.IGNORECASE)
    if labeled_match:
        labeled_total = _extract_delay_minutes(labeled_match.group(1))
        if labeled_total:
            return labeled_total

    hour_match = re.search(r"(\d+)\s*(hour|hours|hr|hrs)", text, re.IGNORECASE)
    minute_match = re.search(r"(\d+)\s*(minute|minutes|min|mins)", text, re.IGNORECASE)

    hours = int(hour_match.group(1)) if hour_match else 0
    minutes = int(minute_match.group(1)) if minute_match else 0
    total = hours * 60 + minutes
    if total > 0:
        return total

    compact_match = re.search(r"delay(?:ed)?\s*(?:by)?\s*(\d{2,3})\s*(?:minutes|min)", text, re.IGNORECASE)
    if compact_match:
        return int(compact_match.group(1))
    return None


def _extract_delay_reason(text: str) -> str:
    labeled_reason = _extract_field(text, [r"Reason Given by Airline", r"Reason"], default="")
    if labeled_reason:
        return labeled_reason

    lowered = text.lower()
    if "technical" in lowered or "maintenance" in lowered:
        return "Technical issues"
    if "weather" in lowered or "storm" in lowered or "snow" in lowered:
        return "Weather disruption"
    if "air traffic control" in lowered:
        return "Air traffic control restrictions"
    if "crew" in lowered:
        return "Crew scheduling issue"
    if "cancel" in lowered:
        return "Flight cancellation"
    if "delay" in lowered:
        return "Flight delay"
    return "Flight disruption detected from Gmail"


def _extract_field(text: str, label_patterns: List[str], default: str = "") -> str:
    for label in label_patterns:
        match = re.search(rf"{label}\s*:\s*(.+)", text, re.IGNORECASE)
        if match:
            return match.group(1).splitlines()[0].strip()
    return default


def _extract_airport(text: str, direction: str) -> str:
    if direction == "departure":
        labeled = _extract_field(text, [r"Departure Airport"], default="")
        if labeled:
            return labeled
        route_match = re.search(r"\b([A-Z]{3})\s*(?:-|->|to)\s*([A-Z]{3})\b", text)
        if route_match:
            return route_match.group(1)
        return "Unknown departure airport"

    labeled = _extract_field(text, [r"Arrival Airport"], default="")
    if labeled:
        return labeled
    route_match = re.search(r"\b([A-Z]{3})\s*(?:-|->|to)\s*([A-Z]{3})\b", text)
    if route_match:
        return route_match.group(2)
    return "Unknown arrival airport"


def _infer_airline(subject: str, sender: str) -> str:
    text = f"{subject} {sender}".lower()
    known_airlines = [
        "lufthansa",
        "british airways",
        "united",
        "american airlines",
        "delta",
        "klm",
        "air france",
        "emirates",
        "qatar",
    ]
    for airline in known_airlines:
        if airline in text:
            return airline.title()
    sender_name = sender.split("<")[0].strip()
    return sender_name or "Airline"


def callback_redirect(success: bool, message: str) -> str:
    status = "connected" if success else "error"
    return f"{_get_frontend_url()}?gmail_status={status}&gmail_message={quote(message)}"
