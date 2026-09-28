# Client Closer Kit delivery

Direct USDT buyers pay **29** (Starter) or **47** (Complete) USDT on **TRON (TRC20)** to `TGiCzRwKLcJWjKXjPzwxJJnBDSuWLE5Wdj`, then email `kuznietsovole@gmail.com` with the kit, amount, txid, and delivery email.

`scripts/deliver_kit.py` drafts that delivery email and a Gmail send recipe. It checks the shape of the email and txid. It does **not** prove the transfer. The Bybit deposit watch does that.

No API keys, OAuth tokens, or kit ZIPs belong in git.

## Human + Bybit watch, then this helper

1. Buyer sends exactly 29 or 47 USDT on TRC20 to the address above (also on the landing page). Wrong network is not a delivery case.
2. Buyer emails `kuznietsovole@gmail.com` with kit (Starter or Complete), amount, txid, and the address that should receive the ZIP.
3. Confirm the deposit with the existing Bybit watch before you draft or send:
   - **Manual:** Bybit → Assets → Deposit records. Coin USDT, network TRC20. Match the buyer’s txid and the amount.
   - **Routine:** use the deposit alert you already run against the Bybit master wallet that receives this TRC20 address. This repo does not call Bybit and does not add a paid chain API.
4. Map the confirmed credit to a tier: **29 → starter**, **47 → complete**. Any other amount: do not deliver. Reply and sort it out first.
5. Run the helper below. Dry-run first. Send only after the product ZIP is on disk and the draft looks right.
6. Each attempt is appended to `logs/deliveries.jsonl`.

Getly checkout is a separate path. This helper is for direct USDT TRC20 only.

## Run

From the repo root, Python 3 stdlib only:

```bash
python3 scripts/deliver_kit.py --dry-run \
  --tier starter \
  --txid 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --delivery-email buyer@example.com \
  --amount 29
```

| Flag | Role |
| --- | --- |
| `--tier` | `starter` or `complete` |
| `--txid` | 64 hex characters. A `0x` prefix is accepted and stripped. A TRON address is rejected. |
| `--delivery-email` | Buyer inbox for the ZIP |
| `--amount` | Optional. When set, it must be 29 for starter or 47 for complete. |
| `--dry-run` | Validate, write the draft, log, do not send. Missing ZIP still exits 0. |
| `--send` | POST to Gmail using `$GMAIL_ACCESS_TOKEN`. Refuses to run without the ZIP. |
| `--allow-duplicate` | Draft or send again after this txid was already `drafted` or `sent`. |

Default mode (neither `--dry-run` nor `--send`) writes the draft and the curl recipe, and exits 0 only when the ZIP is present.

Exit codes: `0` success, `1` invalid input, `2` ZIP missing outside dry-run, `3` send failed or token missing, `4` duplicate txid.

Checks:

```bash
python3 scripts/test_deliver_kit.py
```

GitHub Actions runs the same dry-run on push and pull request (`.github/workflows/delivery-dry-run.yml`).

## Where the ZIP lives

| Tier | Archive | Instructions if it is missing |
| --- | --- | --- |
| starter | `kits/client-closer-kit-starter.zip` | `kits/client-closer-kit-starter.zip.PLACEHOLDER.md` |
| complete | `kits/client-closer-kit-complete.zip` | `kits/client-closer-kit-complete.zip.PLACEHOLDER.md` |

The helper does not build a product archive. If the zip is absent it rewrites the placeholder note and, on `--dry-run`, still prints the email. `kits/*.zip` is gitignored.

Put the real Starter or Complete export at those paths on the machine that sends mail. See `kits/README.md`.

## Email draft and Gmail recipe

A successful run writes:

- `delivery-out/<txid>/email.txt` — `To`, `From`, `Subject`, and plain-text body
- `delivery-out/<txid>/gmail-send.sh` — curl against `gmail.users.messages.send`
- `delivery-out/<txid>/payload.json` — only when the ZIP exists (base64url raw MIME, attachment included)

Default From is `kuznietsovole@gmail.com` (`--from-email` or `$KIT_FROM_EMAIL`). The Gmail token must be allowed to send as that mailbox.

Send recipe (token is **not** stored in the repo):

```bash
export GMAIL_ACCESS_TOKEN="paste-oauth-token-here"   # gmail.send scope; do not commit
delivery-out/<txid>/gmail-send.sh
```

Or let the helper POST it:

```bash
export GMAIL_ACCESS_TOKEN="paste-oauth-token-here"
python3 scripts/deliver_kit.py \
  --tier complete \
  --txid <64-hex-txid> \
  --delivery-email buyer@example.com \
  --amount 47 \
  --send
```

`--dry-run` never contacts Gmail. `delivery-out/` is gitignored (it can contain the product attachment and the buyer address).

## Delivery log

`logs/deliveries.jsonl` gets one JSON object per attempt:

```json
{"amount":"29","date":"2026-09-28T17:00:00Z","email":"buyer@example.com","status":"dry_run_missing_zip","tier":"starter","txid":"0123..."}
```

Required fields are `date`, `tier`, `txid`, `email`, and `status`. Status values include `dry_run`, `dry_run_missing_zip`, `drafted`, `missing_zip`, `sent`, `send_failed`, `duplicate`, and `invalid`.

`logs/` can contain buyer emails. It is gitignored.
