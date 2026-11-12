# PayPal Receipt Scanner API

Upload an image → the API checks whether it is a **PayPal transaction receipt** and, if it is,
returns its details as JSON. One backend serves both your **website** and your **mobile app**.

```
image ──► 1. quality check (size, blur)
      ──► 2. looks like a receipt? (CLIP, optional)
      ──► 3. OCR (EasyOCR)
      ──► 4. is it PayPal? (keywords + 17-char transaction ID)
      ──► 5. extract: transaction ID, amount, currency, fee, date, status,
             sent/received, counterparty, payment method, emails, note
```

## Run it (Windows, PowerShell)

Requires Python 3.10+.

```powershell
cd paypal-receipt-api
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt
copy .env.example .env               # optional settings
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The first start downloads model weights (~700 MB) once. Then open:

- **http://localhost:8000** – demo page: drag in a screenshot and see the result
- **http://localhost:8000/docs** – interactive API docs

Run the tests (no models needed): `pytest`

macOS/Linux: same steps, but activate with `source .venv/bin/activate` and use `cp`.

## API

### `POST /api/v1/receipts/scan`

`multipart/form-data` with one field, **`file`** (JPG, PNG, WEBP or HEIC, ≤10 MB).
Add header `X-API-Key: <key>` if `API_KEY` is set in `.env`.

```bash
curl -F "file=@receipt.png" http://localhost:8000/api/v1/receipts/scan
```

**Accepted** (HTTP 200):
```json
{
  "is_paypal_receipt": true,
  "rejected_at": null,
  "reason": null,
  "confidence": 0.96,
  "complete": true,
  "missing_fields": [],
  "receipt": {
    "transaction_id": "5TY05013RG002845M",
    "direction": "sent",
    "counterparty": "John Doe",
    "amount": 25.0,
    "currency": "USD",
    "fee": null,
    "date": "Nov 3, 2026 at 10:15 AM",
    "status": "Completed",
    "funding_source": "Visa Credit ••••4417",
    "emails": null,
    "note": "Rent share for November"
  },
  "checks": { "quality_ok": true, "looks_like_receipt": true, "mentions_paypal": true, "...": "..." },
  "raw_text": "PayPal\nYou sent $25.00 USD to John Doe\n...",
  "processing_ms": 2140
}
```

**Rejected** (also HTTP 200, because "not a PayPal receipt" is a valid answer):
```json
{
  "is_paypal_receipt": false,
  "rejected_at": "paypal_check",
  "reason": "This looks like a receipt, but not a PayPal one.",
  "receipt": null,
  "...": "..."
}
```
`rejected_at` is `quality`, `classification` or `paypal_check`. `reason` is safe to show to users.
If `complete` is `false`, it's a PayPal receipt but some fields couldn't be read: ask for a clearer screenshot.

**Errors:** `400` not an image / empty, `401` wrong API key, `413` too large, `415` wrong file type.
Body: `{"detail": "..."}`.

### `GET /api/v1/health`
`{"status": "ok", "classifier": true, "ocr": true}`

## Use it from your website and app

Ready-to-copy clients are in `examples/`:

| File | For |
|---|---|
| `examples/web.js` | Any website (plain JS, React, Vue, Next.js) |
| `examples/flutter_receipt_service.dart` | Flutter |
| `examples/android_kotlin.kt` | Native Android (Kotlin + OkHttp) |
| `examples/react_native.js` | React Native / Expo |

**Testing the app against your PC:**
- Android emulator → `http://10.0.2.2:8000`
- Real phone on the same Wi-Fi → `http://<your PC's IP>:8000` (find it with `ipconfig`), and start
  uvicorn with `--host 0.0.0.0`. Allow Python through Windows Firewall if asked.
- Plain `http` on Android needs `android:usesCleartextTraffic="true"` during development.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | empty | If set, requests need `X-API-Key` |
| `CORS_ORIGINS` | `*` | Websites allowed to call the API from the browser. List your domains in production |
| `MAX_UPLOAD_MB` | `10` | Upload limit |
| `RETURN_RAW_TEXT` | `true` | Include OCR text in responses (useful for debugging) |
| `ENABLE_CLASSIFIER` | `true` | CLIP visual check. `false` = lighter server (~600 MB less RAM) |
| `MIN_CLASS_SCORE` | `0.40` | How sure CLIP must be that it's a receipt |
| `OCR_LANGUAGES` | `en` | EasyOCR languages, comma-separated |
| `OCR_GPU` | `false` | Use an NVIDIA GPU for OCR |
| `MIN_KEYWORD_HITS` | `2` | Receipt words needed besides "PayPal"/transaction ID |
| `BLUR_THRESHOLD` | `40` | Lower = accept blurrier photos |

## Deploy

```bash
docker build -t paypal-receipt-api .
docker run -p 8000:8000 --env-file .env paypal-receipt-api
```
Works on Render, Railway, Fly.io, a VPS, etc. Give it at least **2 GB RAM** (or 1 GB with
`ENABLE_CLASSIFIER=false`). Put it behind **HTTPS** in production.

**Security tips**
- Don't put `API_KEY` in website JavaScript, where anyone can read it. For the website, either
  call this API from your own backend, or leave `API_KEY` empty and restrict `CORS_ORIGINS` plus
  add rate limiting at your host/proxy.
- Uploaded images are processed in memory and never saved to disk.

## ⚠️ A screenshot is not proof of payment

Screenshots are easy to edit. This API tells you what the image *says*, not whether the payment
really happened. If you're accepting payments, take the extracted `transaction_id` and confirm it
with **PayPal's Transaction Search API** (on the account that received the money). Check that
amount, currency and status match before trusting it.

## Project layout

```
app/
  main.py        FastAPI app: routes, CORS, API key, upload limits
  service.py     the 5-step pipeline (no web code, easy to reuse)
  parser.py      PayPal text → fields (regex, no ML)
  engines/       CLIP classifier + EasyOCR wrappers (swap for a cloud OCR here)
  schemas.py     JSON response models
  config.py      settings from .env
  static/        demo web page
tests/           pytest suite with fake models
examples/        website + mobile client code
```

## Improving accuracy

- Send me or collect 20–50 real PayPal screenshots (blur private info) and add their OCR text
  to `tests/test_parser.py`; adjust `app/parser.py` until they all pass.
- If OCR struggles on photos of screens, switch the OCR engine to Google Cloud Vision or PaddleOCR
  inside `app/engines/`. The rest of the code doesn't change.
