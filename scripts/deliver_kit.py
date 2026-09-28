#!/usr/bin/env python3
"""Draft a Client Closer Kit delivery email after a confirmed USDT TRC20 deposit.

This does not prove a payment on-chain. Confirm the txid on the existing Bybit
deposit watch first (see DELIVERY.md), then run this helper.

Examples:
  python3 scripts/deliver_kit.py --dry-run \\
    --tier starter \\
    --txid 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \\
    --delivery-email buyer@example.com \\
    --amount 29
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPOSIT_ADDRESS = "TGiCzRwKLcJWjKXjPzwxJJnBDSuWLE5Wdj"
DEFAULT_FROM_EMAIL = "kuznietsovole@gmail.com"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_TOKEN_ENV = "GMAIL_ACCESS_TOKEN"

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+$"
)
TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")

TIERS: dict[str, dict[str, str]] = {
    "starter": {
        "label": "Starter",
        "amount": "29",
        "zip_name": "client-closer-kit-starter.zip",
        "contents": (
            "Notion Client Pipeline, 8 EN + RU close scripts, "
            "the pricing calculator with guide, and the 7-day follow-up cadence."
        ),
    },
    "complete": {
        "label": "Complete",
        "amount": "47",
        "zip_name": "client-closer-kit-complete.zip",
        "contents": (
            "everything in Starter plus 12 objection handlers, "
            "3 filled proposal examples, onboarding and rate-raise scripts, "
            "and the lead-magnet bonus PDF."
        ),
    },
}

FINAL_STATUSES = {"drafted", "sent"}


class DeliveryError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def zip_path_for(tier: str) -> Path:
    return ROOT / "kits" / TIERS[tier]["zip_name"]


def placeholder_path_for(tier: str) -> Path:
    return ROOT / "kits" / f"{TIERS[tier]['zip_name']}.PLACEHOLDER.md"


def placeholder_text(tier: str) -> str:
    spec = TIERS[tier]
    rel_zip = f"kits/{spec['zip_name']}"
    return (
        f"# ZIP placeholder — Client Closer Kit {spec['label']}\n"
        "\n"
        "This file is not the product. Do not send it to a buyer.\n"
        "\n"
        "Expected archive (copy the real kit here; do not invent zip contents):\n"
        "\n"
        f"    {rel_zip}\n"
        "\n"
        f"Tier: {tier}\n"
        f"Price: {spec['amount']} USDT\n"
        "Network: TRON (TRC20)\n"
        f"Deposit address: {DEPOSIT_ADDRESS}\n"
        "\n"
        "How to add the archive:\n"
        f"1. Export the {spec['label']} kit you already sell: {spec['contents']}\n"
        "2. Zip those existing files on your machine.\n"
        "3. Save that zip at the path above. This script only attaches a file it finds.\n"
        "4. `kits/*.zip` is gitignored. Leave the archive out of git when this repo is public.\n"
        "\n"
        "Until that file exists, `scripts/deliver_kit.py --dry-run` can still draft the email.\n"
        "A real send refuses to run without the zip.\n"
    )


def ensure_placeholder(tier: str) -> Path:
    path = placeholder_path_for(tier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(placeholder_text(tier), encoding="utf-8")
    return path


def validate_email(value: str) -> str:
    email = value.strip()
    if not email or any(ch in email for ch in "\r\n\t "):
        raise DeliveryError(f"Invalid delivery email: {value!r}")
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise DeliveryError(f"Invalid delivery email: {value!r}")
    return email


def validate_txid(value: str) -> str:
    raw = value.strip()
    if any(ch in raw for ch in "\r\n\t "):
        raise DeliveryError("Invalid txid: remove spaces and line breaks.")
    if TRON_ADDRESS_RE.fullmatch(raw):
        raise DeliveryError(
            "That value is a TRON address, not a transaction id. "
            "Paste the 64-character txid from the buyer email."
        )
    txid = raw[2:] if raw.lower().startswith("0x") else raw
    if not TXID_RE.fullmatch(txid):
        raise DeliveryError(
            "Invalid txid. Expected 64 hex characters (optional 0x prefix). "
            "This is a format check, not an on-chain proof."
        )
    return txid.lower()


def validate_tier(value: str) -> str:
    tier = value.strip().lower()
    if tier not in TIERS:
        raise DeliveryError("Invalid tier. Use starter or complete.")
    return tier


def parse_amount(value: str) -> Decimal:
    cleaned = value.strip().lower().replace("usdt", "").replace(",", "").strip()
    if not cleaned:
        raise DeliveryError("Amount is empty.")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise DeliveryError(f"Invalid amount: {value!r}") from exc
    return amount


def expected_amount(tier: str) -> Decimal:
    return Decimal(TIERS[tier]["amount"])


def resolve_amount(tier: str, amount: str | None) -> tuple[Decimal, str]:
    expected = expected_amount(tier)
    if amount is None or amount.strip() == "":
        return expected, "tier_default"
    parsed = parse_amount(amount)
    if parsed != expected:
        raise DeliveryError(
            f"Amount {parsed} USDT does not match {tier} "
            f"({expected} USDT). Do not deliver this tier."
        )
    return parsed, "cli"


def build_subject(tier: str) -> str:
    return f"Your Client Closer Kit ({TIERS[tier]['label']}) is ready"


def build_body(tier: str, txid: str, amount: Decimal) -> str:
    spec = TIERS[tier]
    return (
        "Hello,\n"
        "\n"
        f"Your Client Closer Kit ({spec['label']}) is attached.\n"
        "\n"
        f"Tier: {spec['label']}\n"
        f"Amount: {amount} USDT\n"
        "Network: TRON (TRC20)\n"
        f"Transaction: {txid}\n"
        "\n"
        f"This tier includes {spec['contents']}\n"
        "\n"
        "If the scripts do not fit your niche, reply within 14 days of this email "
        "and ask for a refund with these order details. That is a fit refund. "
        "It is not a promise of clients, revenue, or a closing rate.\n"
        "\n"
        "If the attachment does not open, reply to this message.\n"
        "\n"
        "Client Closer Kit\n"
    )


def render_email_file(from_email: str, to_email: str, subject: str, body: str) -> str:
    return f"To: {to_email}\nFrom: {from_email}\nSubject: {subject}\n\n{body}"


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_mime(from_email: str, to_email: str, subject: str, body: str, zip_path: Path) -> bytes:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = from_email
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        zip_path.read_bytes(),
        maintype="application",
        subtype="zip",
        filename=zip_path.name,
    )
    return message.as_bytes()


def gmail_payload(raw_message: bytes) -> str:
    encoded = base64.urlsafe_b64encode(raw_message).decode("ascii").rstrip("=")
    return json.dumps({"raw": encoded}, separators=(",", ":"))


def write_send_recipe(out_dir: Path, zip_path: Path, payload_ready: bool) -> Path:
    recipe = out_dir / "gmail-send.sh"
    quoted_zip = sh_single_quote(str(zip_path))
    payload_check = ""
    if not payload_ready:
        payload_check = (
            'echo "payload.json was not written because the product ZIP is missing." >&2\n'
            "exit 1\n"
        )
    script = (
        "#!/bin/sh\n"
        "# Gmail API send recipe. Review email.txt before you run this.\n"
        "# The access token stays in the environment. Do not paste it into this file.\n"
        "set -eu\n"
        'cd "$(dirname "$0")"\n'
        f'ZIP_FILE={quoted_zip}\n'
        f'if [ -z "${{{GMAIL_TOKEN_ENV}:-}}" ]; then\n'
        f'  echo "Set {GMAIL_TOKEN_ENV} to an OAuth token with gmail.send. Do not commit it." >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [ ! -f "$ZIP_FILE" ]; then\n'
        '  echo "Refusing to send. Product ZIP not found: $ZIP_FILE" >&2\n'
        '  echo "See the .PLACEHOLDER.md next to that path." >&2\n'
        "  exit 1\n"
        "fi\n"
        f"{payload_check}"
        'if [ ! -f payload.json ]; then\n'
        '  echo "payload.json is missing. Re-run scripts/deliver_kit.py after the ZIP is in place." >&2\n'
        "  exit 1\n"
        "fi\n"
        "curl -sS --fail-with-body -X POST \\\n"
        f'  "{GMAIL_SEND_URL}" \\\n'
        f'  -H "Authorization: Bearer ${{{GMAIL_TOKEN_ENV}}}" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        "  --data-binary @payload.json\n"
        'echo\n'
    )
    recipe.write_text(script, encoding="utf-8")
    recipe.chmod(0o755)
    return recipe


def clip(value: object, limit: int = 300) -> object:
    if not isinstance(value, str):
        return value
    flattened = value.replace("\r", " ").replace("\n", " ")
    if len(flattened) <= limit:
        return flattened
    return flattened[:limit] + "..."


def append_log(log_path: Path, record: dict[str, object]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    safe = {key: clip(value) for key, value in record.items()}
    line = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prior_final_status(log_path: Path, txid: str) -> str | None:
    if not log_path.is_file():
        return None
    found: str | None = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("txid") == txid and row.get("status") in FINAL_STATUSES:
            found = str(row.get("status"))
    return found


def send_via_gmail(payload_path: Path) -> str:
    token = os.environ.get(GMAIL_TOKEN_ENV, "").strip()
    if not token:
        raise DeliveryError(
            f"{GMAIL_TOKEN_ENV} is not set. The curl recipe was written; nothing was sent.",
            code=3,
        )
    request = urllib.request.Request(
        GMAIL_SEND_URL,
        data=payload_path.read_bytes(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise DeliveryError(f"Gmail API HTTP {exc.code}: {detail}", code=3) from exc
    except urllib.error.URLError as exc:
        raise DeliveryError(f"Gmail API request failed: {exc.reason}", code=3) from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return ""
    message_id = parsed.get("id")
    return str(message_id) if message_id else ""


def log_and_return(
    log_path: Path,
    base: dict[str, object],
    status: str,
    code: int,
    message: str,
) -> int:
    record = dict(base)
    record["date"] = utc_now()
    record["status"] = status
    if message and status in {"invalid", "duplicate", "send_failed", "missing_zip"}:
        record["detail"] = message
    append_log(log_path, record)
    stream = sys.stdout if code == 0 else sys.stderr
    print(message, file=stream)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", required=True, help="starter or complete")
    parser.add_argument("--txid", required=True, help="64-hex TRON transaction id")
    parser.add_argument("--delivery-email", required=True, help="Where the ZIP should be emailed")
    parser.add_argument("--amount", help="Optional USDT amount. Must match the tier when set.")
    parser.add_argument(
        "--from-email",
        default=os.environ.get("KIT_FROM_EMAIL", DEFAULT_FROM_EMAIL),
        help=f"From address (default {DEFAULT_FROM_EMAIL}, or KIT_FROM_EMAIL)",
    )
    parser.add_argument(
        "--zip",
        dest="zip_path",
        help="Override the kit zip path. Default is kits/client-closer-kit-<tier>.zip",
    )
    parser.add_argument(
        "--log",
        dest="log_path",
        default=str(ROOT / "logs" / "deliveries.jsonl"),
        help="JSONL delivery log (default logs/deliveries.jsonl)",
    )
    parser.add_argument(
        "--out",
        dest="out_dir",
        help="Draft directory (default delivery-out/<txid>)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate, draft, and log. Do not send. Missing ZIP still exits 0.",
    )
    mode.add_argument(
        "--send",
        action="store_true",
        help=f"POST the Gmail API payload using ${GMAIL_TOKEN_ENV}. Requires the ZIP.",
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Draft or send again when this txid was already drafted or sent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_path = Path(args.log_path)
    base: dict[str, object] = {
        "date": utc_now(),
        "tier": (args.tier or "").strip().lower(),
        "txid": (args.txid or "").strip(),
        "email": (args.delivery_email or "").strip(),
        "status": "invalid",
    }

    try:
        tier = validate_tier(args.tier)
        email = validate_email(args.delivery_email)
        txid = validate_txid(args.txid)
        from_email = validate_email(args.from_email)
        amount, amount_source = resolve_amount(tier, args.amount)
    except DeliveryError as exc:
        base["date"] = utc_now()
        append_log(log_path, {**base, "status": "invalid", "detail": str(exc)})
        print(str(exc), file=sys.stderr)
        return exc.code

    base.update(
        {
            "tier": tier,
            "txid": txid,
            "email": email,
            "amount": str(amount),
            "amount_source": amount_source,
        }
    )

    zip_path = Path(args.zip_path) if args.zip_path else zip_path_for(tier)
    if not zip_path.is_absolute():
        zip_path = (Path.cwd() / zip_path).resolve()
    placeholder = ensure_placeholder(tier)
    zip_present = zip_path.is_file()

    if not args.dry_run and not args.allow_duplicate:
        previous = prior_final_status(log_path, txid)
        if previous:
            return log_and_return(
                log_path,
                base,
                "duplicate",
                4,
                f"txid {txid} already has status {previous}. Pass --allow-duplicate to draft again.",
            )

    subject = build_subject(tier)
    body = build_body(tier, txid, amount)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "delivery-out" / txid
    out_dir.mkdir(parents=True, exist_ok=True)
    email_file = out_dir / "email.txt"
    draft = render_email_file(from_email, email, subject, body)
    if not zip_present:
        draft = (
            f"OPS-ONLY: do not send. ZIP missing at {zip_path}. See {placeholder}.\n\n"
            + draft
        )
    email_file.write_text(draft, encoding="utf-8")

    payload_path = out_dir / "payload.json"
    if zip_present:
        payload_path.write_text(
            gmail_payload(build_mime(from_email, email, subject, body, zip_path)),
            encoding="utf-8",
        )
    elif payload_path.exists():
        payload_path.unlink()

    recipe = write_send_recipe(out_dir, zip_path, payload_ready=zip_present)

    if not zip_present and not args.dry_run:
        print(email_file.read_text(encoding="utf-8"))
        return log_and_return(
            log_path,
            base,
            "missing_zip",
            2,
            f"ZIP missing at {zip_path}. Instructions: {placeholder}. Email draft: {email_file}",
        )

    status = "dry_run" if args.dry_run and zip_present else "drafted"
    if args.dry_run and not zip_present:
        status = "dry_run_missing_zip"

    gmail_id = ""
    if args.send:
        try:
            gmail_id = send_via_gmail(payload_path)
        except DeliveryError as exc:
            append_log(
                log_path,
                {
                    **base,
                    "date": utc_now(),
                    "status": "send_failed",
                    "detail": str(exc),
                    "zip_present": zip_present,
                },
            )
            print(str(exc), file=sys.stderr)
            return exc.code
        status = "sent"

    record: dict[str, object] = {
        **base,
        "date": utc_now(),
        "status": status,
        "zip_present": zip_present,
        "zip_path": str(zip_path),
    }
    if gmail_id:
        record["gmail_id"] = gmail_id
    append_log(log_path, record)

    print(f"status: {status}")
    print(f"zip: {zip_path} ({'found' if zip_present else 'missing'})")
    if not zip_present:
        print(f"placeholder: {placeholder}")
    print(f"email_file: {email_file}")
    print(f"recipe: {recipe}")
    print(f"log: {log_path}")
    print()
    print(email_file.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
