#!/usr/bin/env python3
"""Stdlib checks for the delivery helper. No network."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "deliver_kit.py"
sys.path.insert(0, str(ROOT / "scripts"))

import deliver_kit  # noqa: E402

VALID_TXID = "ab" * 32
OTHER_TXID = "cd" * 32


class ValidationTests(unittest.TestCase):
    def test_email_and_txid(self) -> None:
        self.assertEqual(deliver_kit.validate_email("buyer@example.com"), "buyer@example.com")
        with self.assertRaises(deliver_kit.DeliveryError):
            deliver_kit.validate_email("not-an-email")
        with self.assertRaises(deliver_kit.DeliveryError):
            deliver_kit.validate_email("buyer@example.com\nBcc: evil@example.com")

        self.assertEqual(deliver_kit.validate_txid("0x" + VALID_TXID.upper()), VALID_TXID)
        with self.assertRaises(deliver_kit.DeliveryError):
            deliver_kit.validate_txid(deliver_kit.DEPOSIT_ADDRESS)
        with self.assertRaises(deliver_kit.DeliveryError):
            deliver_kit.validate_txid("abc123")

    def test_amount_must_match_tier(self) -> None:
        amount, source = deliver_kit.resolve_amount("starter", None)
        self.assertEqual(amount, deliver_kit.expected_amount("starter"))
        self.assertEqual(source, "tier_default")
        amount, source = deliver_kit.resolve_amount("complete", "47 USDT")
        self.assertEqual(str(amount), "47")
        self.assertEqual(source, "cli")
        with self.assertRaises(deliver_kit.DeliveryError):
            deliver_kit.resolve_amount("starter", "47")

    def test_placeholder_names_the_zip_path(self) -> None:
        text = deliver_kit.placeholder_text("starter")
        self.assertIn("kits/client-closer-kit-starter.zip", text)
        self.assertNotIn("PK\x03\x04", text)


class CliTests(unittest.TestCase):
    def test_dry_run_exits_zero_without_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "deliveries.jsonl"
            out_dir = Path(tmp) / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--dry-run",
                    "--tier",
                    "starter",
                    "--txid",
                    VALID_TXID,
                    "--delivery-email",
                    "buyer@example.com",
                    "--amount",
                    "29",
                    "--log",
                    str(log_path),
                    "--out",
                    str(out_dir),
                    "--zip",
                    str(Path(tmp) / "missing.zip"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status: dry_run_missing_zip", result.stdout)
            self.assertIn("OPS-ONLY: do not send", result.stdout)
            self.assertIn("Subject: Your Client Closer Kit (Starter) is ready", result.stdout)
            row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(
                sorted(["date", "email", "status", "tier", "txid"]),
                sorted(key for key in ("date", "tier", "txid", "email", "status") if key in row),
            )
            self.assertEqual(row["status"], "dry_run_missing_zip")
            recipe = (out_dir / "gmail-send.sh").read_text(encoding="utf-8")
            self.assertIn("${GMAIL_ACCESS_TOKEN}", recipe)
            self.assertNotIn("ya29.", recipe)
            self.assertNotIn("Bearer ya", recipe)
            self.assertFalse((out_dir / "payload.json").exists())

    def test_dry_run_with_zip_writes_recipe_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "kit.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("README.txt", "fixture only\n")
            log_path = Path(tmp) / "deliveries.jsonl"
            out_dir = Path(tmp) / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--dry-run",
                    "--tier",
                    "complete",
                    "--txid",
                    OTHER_TXID,
                    "--delivery-email",
                    "buyer@example.com",
                    "--log",
                    str(log_path),
                    "--out",
                    str(out_dir),
                    "--zip",
                    str(archive),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status: dry_run", result.stdout)
            payload = json.loads((out_dir / "payload.json").read_text(encoding="utf-8"))
            self.assertIn("raw", payload)
            self.assertNotIn("GMAIL_ACCESS_TOKEN=", (out_dir / "gmail-send.sh").read_text(encoding="utf-8"))

    def test_invalid_email_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--dry-run",
                    "--tier",
                    "starter",
                    "--txid",
                    VALID_TXID,
                    "--delivery-email",
                    "not-an-email",
                    "--log",
                    str(Path(tmp) / "deliveries.jsonl"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            row = json.loads((Path(tmp) / "deliveries.jsonl").read_text(encoding="utf-8").strip())
            self.assertEqual(row["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
