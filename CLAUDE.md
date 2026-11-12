# Khataz — notes for Claude Code

Shared business credit ledger with PayPal payment verification. FastAPI + SQLAlchemy 2 +
Alembic + PostgreSQL in `backend/`, React + Vite (plain JS) in `frontend/`. Hackathon project.

## Rules that must not be broken
- Money is `Decimal` / `Numeric(18,2)`, never float. API sends money as strings.
- Balances are computed from `ledger_entries.delta`; never store a balance.
- Ledger entries are never edited or deleted. Fix mistakes with reversal or adjustment entries.
- Only `app/services/ledger.py` creates ledger entries. Every balance change writes an audit log.
- Disputed and voided entries don't count in the balance.
- A payment claim reduces a debt only after the recipient confirms it; mismatches go to review.
- One PayPal transaction / screenshot is counted once per recipient (unique constraints).
- Payer identity and debtor identity are separate; a different payer needs the recipient's approval.
- All times stored in UTC; shown in the user's time zone.
- Every endpoint checks access through `services/common.py` (`owned_business`, `relationship_for`).
- AI features (when added) only propose entries; a person confirms before anything is saved.

## Commands
- Tests: `cd backend && pytest` (SQLite) — add tests for every rule you touch.
- Migrations: change `app/models.py`, then `alembic revision --autogenerate -m "..."`, review it, `alembic upgrade head`.
- Frontend: `cd frontend && npm run dev`; `npm run build` must pass.

## Style
- Colours: PayPal navy `#003087`, blue `#0070E0`, light blue `#009CDE`, white, black (see `frontend/src/styles.css`).
- Blue amounts = owed to me, black = I owe. Keep user-facing text short and plain.
