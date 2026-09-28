# Client Closer Kit

Static landing for **Client Closer Kit**.

Live (after GitHub Pages is enabled on `main` / root):

https://gangsstar3.github.io/client-closer-kit/

## Delivery

After the Bybit deposit watch confirms a USDT TRC20 payment, draft the buyer email with the stdlib helper. Details, ZIP paths, and the Gmail curl recipe are in [DELIVERY.md](DELIVERY.md).

```bash
python3 scripts/deliver_kit.py --dry-run \
  --tier starter \
  --txid 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --delivery-email buyer@example.com \
  --amount 29
```
