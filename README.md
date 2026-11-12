# Khataz

A shared credit ledger (khata) for small businesses. Record who owes what, let both sides see the
same record, and confirm PayPal payments before they change a balance. Khataz records payments;
it never moves money.

```
docker-compose.yml   PostgreSQL for development
backend/             FastAPI + SQLAlchemy + Alembic (API on port 8000)
frontend/            React + Vite (web app on port 5173)
```

## First-time setup (Windows, PowerShell)

You need Docker Desktop, Python 3.11+ and Node.js 20+.

**1. Start the database** (from this folder):
```powershell
docker compose up -d
```

**2. Backend** (new terminal):
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head          # creates the tables
python -m scripts.seed        # optional: demo users and records
uvicorn app.main:app --reload
```
API docs: http://localhost:8000/docs

**3. Frontend** (another terminal):
```powershell
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173**.

Demo logins after seeding (password `password123`): `abdul@khataz.demo` (owner of Milk Supply and
Electronics Store, 9 people, weeks of history, an entry and a PayPal payment waiting, a chat),
`marwan@khataz.demo` (customer of Milk Supply), `faizan@khataz.demo` (customer of Electronics Store).

To start over with fresh demo data (this deletes everything in the database):
```powershell
alembic downgrade base
alembic upgrade head
python -m scripts.seed
```

Forgot password: "Forgot password?" on the log-in page sends a reset link by email. Without the
SMTP settings the link is printed in the backend terminal instead.

## Every day after that

```powershell
docker compose up -d                                   # database
cd backend; .venv\Scripts\Activate.ps1; uvicorn app.main:app --reload
cd frontend; npm run dev                               # second terminal
```

## Sending invite emails (optional)

"Invite to Khataz" on a record emails the person a sign-up link. Without email settings the
invite is still saved, and the app shows the link so you can send it yourself (WhatsApp, SMS).
To send real emails, fill in the `SMTP_...` lines in `backend/.env` and restart the backend.
With Gmail: turn on 2-step verification, create an **app password** at
https://myaccount.google.com/apppasswords, and use it as `SMTP_PASSWORD`
(`SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER` = your Gmail address).

## Screenshot scanner (optional)

Without it, people type the receipt details by hand and everything else works. To read PayPal
screenshots automatically (CLIP + EasyOCR, about 2 GB download):
```powershell
cd backend
pip install -r requirements-scanner.txt
```
The models load on the first scan, which takes a while once.

## Type an entry (AI, free)

On the dashboard, type a note like `Marwan took 5 kg milk for $20`, `CUST-002 paid 15 cash` or
`Ali ne 500 rupees jama karaye`, or `marvan took 5 kg milk from Gujjar Milk Shop`. Khataz finds
the business, the person (small typos are fine), add or subtract, the amount and what it was for,
and shows it to check before anything is saved:
- someone with that name already has a record: it asks "add to their record, or create a new one?"
- nobody has that name: it fills in a new record (name, next free ID like CUST-004, business,
  customer or supplier) and creates it together with the entry.

It tries **Groq**, then **OpenRouter** (both free, no card), then a built-in reader that needs no
internet, so it always works. Add keys to `backend/.env` to use the AI:
```
GROQ_API_KEY=<from console.groq.com -> API Keys>
GROQ_MODEL=openai/gpt-oss-120b          # or any model on Groq's Models page
OPENROUTER_API_KEY=<optional backup>
OPENROUTER_MODEL=<a model id ending in :free>
```
The check window shows which one read the note (Groq, OpenRouter or Built-in).

### Checking entries on shared records

When the owner adds money to a shared record, the other person gets a notification and the entry
shows **Check it · 23h left** for them. Within **24 hours** they can **Accept** it or **Cancel** it
with a reason. A cancel removes it from the balance at once and tells the owner why. After 24 hours
the entry is **Final** and can't be cancelled (mistakes are then fixed by the owner with Reverse or
Update money). Change the window with `ENTRY_CANCEL_HOURS` in `backend\.env`.

### The assistant

The ✦ button at the bottom right of every page opens the Khataz assistant (Groq). It answers
questions about using Khataz, and takes entries in a conversation: if something is missing (the
amount, or who it's for) it asks, then shows a card to check and save. Without an AI key it still
does entries with the built-in reader.

### Voice

Tap 🎤 in the assistant and speak, then tap ■. Groq Whisper turns the speech into text (English,
Urdu and mixed); without a Groq key, browsers that have built-in speech recognition (Chrome, Edge)
are used instead. Replies to spoken requests are read aloud. You can say:
- "Marwan took 5 kg milk for 20 dollars" → entry to check and save (asks for anything missing)
- "Set Marwan's balance to 80" → Update money, from the old balance to the new one
- "Undo Marwan's last entry" → reverses it (entries are never deleted, the reversal is kept)
- "Delete Marwan's record" → removes it from the lists, only when the balance is zero
Nothing changes until you tap **Confirm** (or **Check and save** for entries). Only the business
owner can do these tasks. Optional setting: `GROQ_STT_MODEL` (default `whisper-large-v3-turbo`).

## Chats

**Chats** (top menu, or the bottom bar on phones) lets Khataz users message each other privately.
Start a chat with someone's @Khataz ID, or press **Message** on a shared record. New messages show
as a badge on Chats and appear within a few seconds; "Seen" shows when your last message was read.
(The app checks for new messages every few seconds; no extra server needed.)

## Email notifications

With the `SMTP_...` settings filled in (see "Sending invite emails"), people also get an email for
payments to confirm, confirmations, disputes and reviews, with a button to the record. Each person
can turn this off in Settings. Emails go out only after the change is saved.

## PayPal: verified sender + automatic confirmation (sandbox)

Two features, both off until you add PayPal app keys to `backend/.env`:

- **Connect with PayPal** (Profile → PayPal account). PayPal tells Khataz the person's real
  PayPal email and account ID. Every receipt a debtor sends then carries that verified sender,
  and a debtor can't send a receipt until they've connected.
- **Automatic payment check** (Profile → Automatic payment check, for the receiver). The receiver
  saves the Client ID + Secret of *their own* PayPal app. Every `PAYPAL_SYNC_SECONDS` (and on
  "Check PayPal now") Khataz reads their PayPal transactions and confirms a pending receipt when it
  finds a completed incoming payment from the verified sender, in the same currency, within the
  payment tolerance, and not used before. PayPal can take a few minutes (up to 3 hours) to list a
  new payment.

### Setup (about 10 minutes)

1. Sign in at https://developer.paypal.com → **Apps & Credentials** (Sandbox) → **Create App**
   (type Merchant). Copy its **Client ID** and **Secret**.
2. In the app, under **Features**, tick **Log in with PayPal** → **Advanced settings**:
   - Return URL: `http://localhost:5173/paypal/callback`. If PayPal refuses it, use
     `https://example.com` instead (see step 4).
   - Information requested: **Full name**, **Email**, **PayPal account ID (payer ID)**,
     **Account verification status**. Fill the privacy/user-agreement URLs (any URL works in sandbox).
3. Also tick **Transaction search** for the app. Save.
4. In `backend/.env`:
   ```
   PAYPAL_ENV=sandbox
   PAYPAL_CLIENT_ID=<client id>
   PAYPAL_CLIENT_SECRET=<secret>
   PAYPAL_REDIRECT_URI=http://localhost:5173/paypal/callback   # or https://example.com
   ```
   With `https://example.com`, PayPal sends you to example.com after you approve: copy that whole
   link from the address bar and paste it into **Profile → PayPal account → Finish connecting**.
5. `pip install -r requirements.txt` (adds `cryptography`, used to store secrets encrypted),
   `alembic upgrade head`, restart the backend.

### Demo

- **Testing Tools → Sandbox Accounts** has a Personal (buyer) and a Business account. The Business
  account is the one that owns your app.
- Debtor (e.g. @marwan): Profile → **Connect with PayPal** → log in as the **Personal** sandbox account.
- Receiver (e.g. @abdul): Profile → **Automatic payment check** → paste the app's Client ID + Secret.
- At https://www.sandbox.paypal.com, as the Personal account, send money to the Business account's
  email. Upload that receipt in Khataz as Marwan. Within a few minutes (or on **Check PayPal now**)
  Abdul's record shows **Confirmed by PayPal** and the balance drops.

Note: reading many receivers' accounts through one app needs PayPal's partner programme; here each
receiver uses their own app keys, which needs no approval.

## Changing the database

1. Edit `backend/app/models.py`
2. `alembic revision --autogenerate -m "what changed"`
3. Check the new file in `backend/alembic/versions/`, then `alembic upgrade head`
4. Commit the migration file

Start over with an empty database: `alembic downgrade base` then `alembic upgrade head`.

## Tests

```powershell
cd backend
pytest                       # fast, uses SQLite in memory
$env:TEST_DATABASE_URL="postgresql+psycopg://khataz:khataz_dev@localhost:5432/khataz_test"; pytest
```
For the PostgreSQL run, create the test database once:
`docker compose exec db createdb -U khataz khataz_test`.

## How it works

**Books.** Each business has two books: *Money Owed to Me* (receivable) and *Money I Owe*
(payable). One person can be in both, and in several businesses, with separate balances.

**Balances** are always summed from ledger entries, never stored. Entries are never edited or
deleted: mistakes are fixed with a reversal or a correction entry, and every change goes to the
audit log (the *History* tab).

**Two-sided records.** The owner invites a contact by email. When the contact accepts from their own
account, both see the same record. The contact can accept or dispute each entry; disputed entries
don't count in the balance until the owner keeps or cancels them.

**PayPal payments.** A screenshot is only a claim.
1. The payer uploads the screenshot. The scanner checks it's a PayPal receipt and pre-fills the form;
   the payer corrects it and submits.
2. Duplicates are refused (same transaction ID or same image for the same recipient).
3. The recipient checks their own PayPal and answers *received*, *different amount* or *not received*.
4. It's applied automatically only if the amount arrived within the tolerance (95% by default,
   for fees and conversion), the payer is the debtor, the payee matches, and the status is Completed.
   Anything else goes to the recipient's **Review** page to apply, hold or reject.
5. A later refund or chargeback is recorded as a reversal.

**Currencies.** Each record keeps its own currency. Payments in another currency are converted at
that day's rate (frankfurter.app, falling back to open.er-api.com), and the rate is saved with the
payment. The recipient can also type a rate.

**Time zones.** Everything is stored in UTC and shown in each user's own time zone (Settings).
A receipt time is read in the submitter's time zone.

## Main API routes

| Route | What |
| --- | --- |
| `POST /api/auth/register`, `/api/auth/login` | Account and JWT |
| `GET /api/dashboard` | Both books, grouped by business, with totals |
| `POST /api/businesses`, `POST /api/businesses/{id}/contacts` | Add business, add person |
| `GET /api/relationships/{id}` | One record: balance, entries, claims, disputes |
| `POST /api/relationships/{id}/entries` | Credit, payment or correction (owner) |
| `POST /api/entries/{id}/accept`, `/dispute`, `/reverse` | Entry actions |
| `POST /api/relationships/{id}/invite`, `/api/invites/{id}/accept` | Link accounts |
| `POST /api/relationships/{id}/claims/scan`, `/claims` | PayPal screenshot claim |
| `POST /api/claims/{id}/respond`, `/resolve`, `/reverse` | Recipient's decision |
| `GET /api/review`, `/api/notifications` | What's waiting for you |

Full, interactive list at http://localhost:8000/docs.

## Deploying

- **Backend:** `backend/Dockerfile` (runs migrations on start). Set `DATABASE_URL`, a long random
  `JWT_SECRET` and `CORS_ORIGINS` to your frontend's address. Use a managed PostgreSQL
  (Render, Railway, Neon, Supabase).
- **Frontend:** `npm run build`, host `frontend/dist` (Vercel, Netlify). Set `VITE_API_URL` to the
  backend's URL before building.

## Not built yet

A native mobile app. The web app works on phones (bottom navigation, stacked ledger rows), and a
native app could use the same API.
