# Partner CRM API

Backend for the CCP Partnerships frontends in the `partner-crm` monorepo. It follows the S074
comms-service architecture: FastAPI, async SQLAlchemy 2.0, Alembic, PostgreSQL, Celery on Redis.
Authentication is **email and password** with server-side sessions. There is no Zitadel or IAM
dependency.

| System | Module | Routes (under `/api/v1`) |
| --- | --- | --- |
| S081 | Stakeholder / Partner CRM | `/stakeholders`, `/stakeholder-contacts`, `/segments` |
| S082 | MOU & Partnership Lifecycle Tracker | `/partnerships`, `/partnership-obligations`, `/partnership-reviews`, `/partnership-renewal-alerts`, `/partnership-audit-events` |
| S083 | International Relations & Protocols | `/ir/engagements`, `/ir/correspondence`, `/ir/letter-templates`, `/ir/gifts` |
| S088 | Public Survey / Consultation | `/consultations`, `/consultation-responses`, public: `/public/consultations` |
| S091 | Donor / Annual-Report Microsites | `/microsites`, `/microsite-templates`, public: `/public/microsites` |
| S092 | KOL & Thought-Leader Tracker | `/kols`, `/kol-engagements`, `/kol-content`, `/kol-mentions` |
| S084 | Visa & Travel Authorisation | `/travel-requests`, `/travel-policy` |
| Platform | Auth, users, audit | `/auth/*`, `/users`, `/roles`, `/audit-events` |

The request and response shapes are the TypeScript contracts in `partner-crm/packages/types`, and the
endpoint map is `partner-crm/packages/api-client`. Business rules for S083, S091 and S092 are in
`partner-crm/docs/architecture/new-module-rules.md`. The S082 contract is in
`partner-crm/docs/architecture/s082-backend-contract.md`.

## Layout

```text
app/
  main.py              FastAPI app, middleware, exception handlers, /healthz, /readyz
  api/v1/router.py     the module registry; each context is mounted in isolation
  api/v1/<module>.py   one router per bounded context; routers own transactions
  core/                config, database, auth (sessions), rbac, errors, middleware, audit, rate limit
  models/              SQLAlchemy models (portable types: Uuid, JSON→JSONB on PostgreSQL)
  schemas/             Pydantic models, camelCase JSON via CamelModel
  services/            business rules (state machines, guards, derivations)
  tasks/jobs.py        Celery jobs: outbox relay and lifecycle sweeps
alembic/               async env; 0001 creates the schema, audit triggers and template data
scripts/               seed.py (reference and demo data), create_user.py
tests/integration/     HTTP-level tests through httpx.AsyncClient
```

## Run locally without Docker

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env    # then set DATABASE_URL, SECRET_KEY, BOOTSTRAP_ADMIN_PASSWORD
alembic upgrade head
python -m scripts.seed            # templates and the bootstrap administrator
python -m scripts.seed --demo     # optional: demo users (password Clet-Demo-2026!) and records
uvicorn app.main:app --reload --port 8000
```

For a quick trial without PostgreSQL, set `DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3`. SQLite is
for development and tests only, and production refuses to start with it.

With `DEBUG=true`, interactive API docs are at `http://localhost:8000/api/v1/docs`.

## Run with Docker

```bash
cp .env.example .env
docker compose up --build              # db, redis, migrate, api, worker, beat
docker compose run --rm api python -m scripts.seed --demo
```

## Connect the frontends

Every Vite app proxies `/api` to `http://localhost:8000`, so the browser sees one origin and the
HTTP-only cookie works. In the app's `.env.local`:

```text
VITE_AUTH_MODE=api
VITE_AUTH_API_URL=/api/v1/auth
VITE_DATA_MODE=api
VITE_API_URL=/api/v1
```

Then run the app, for example `pnpm dev --filter @partner-crm/partner-portal`, and sign in with a seeded
account.

## Module isolation

The five frontends are released separately, so one bounded context must not be
able to take the others down. `app/api/v1/router.py` imports each module inside
its own guard:

- a module that imports cleanly is mounted as usual;
- a module that fails to import is logged, and **only its own route prefixes**
  answer `503 MODULE_UNAVAILABLE` with the module and system named, and
  `retryable: true`;
- every other module keeps serving, so a bad S084 deploy leaves S081, S082,
  S083, S088 and S091 untouched.

`GET /api/v1/modules` reports the state, which portals each context serves, and
the import error when there is one:

```bash
curl -s localhost:8000/api/v1/modules | jq '.data[] | {module, system, loaded}'
```

The frontends match this: each app's provider surfaces the failure as a banner
with a retry rather than an empty screen, so an outage in one portal reads as an
outage rather than as "no work outstanding". `tests/unit/test_module_isolation.py`
drives a deliberately broken module and asserts all of the above.

## Authentication and security

- `POST /auth/login` `{email, password}` returns `{user}` and sets `pcrm_session`. The cookie is
  HTTP-only, SameSite=Lax, and Secure outside development.
- `GET /auth/session` returns `{user}` or `401`. `POST /auth/logout` revokes the session. `POST /auth/password` changes the password and revokes your other sessions.
- Passwords are hashed with Argon2id. Only the SHA-256 digest of each session token is stored.
  Sessions expire after 120 idle minutes or 12 hours.
- After 5 failed logins the account locks for 15 minutes. Unknown emails and wrong passwords get the same response.
- CSRF protection: SameSite cookies, and an `Origin`/`Referer` allow-list (`ALLOWED_ORIGINS`) on every
  state-changing request.
- Every user has one role, and `app/core/rbac.py` maps roles to permissions. The role names match the frontend
  `permissions.ts` files. Account admin (`/users`) needs `System Administrator`.
- Public endpoints (consultation submissions, microsite unlocks and views) are rate-limited per IP.
  They use Redis when it is reachable and in-process counters otherwise.
- Restricted microsites are unlocked with a signed, HTTP-only cookie tied to the current access code.
  Changing the code revokes every earlier unlock.

Create an administrator without demo data:

```bash
python -m scripts.create_user --email you@clet.gov.gh --name "Your Name" --role "System Administrator"
```

## Audit and integrations

- Every change writes a hash-chained `pcrm_audit_event`. On PostgreSQL, triggers block UPDATE and
  DELETE. `GET /audit-events/integrity` recomputes the chain.
- Integration messages (S074 notifications, S203 screening requests, S204 audit, S011 gift flags, S225 analytics, and S084,
  S078 and S086 handoffs) go into `pcrm_outbox_event` in the same transaction. They are keyed by an
  idempotency key, so a retry never duplicates them. The Celery job `pcrm.relay_outbox` delivers them
  with exponential backoff. A target with no URL configured stays pending and never blocks the business record.
- Beat schedule:
  - outbox relay every 15 s
  - S082 sweep daily: RENEWAL_DUE inside 90 days, EXPIRED after expiry, due renewal alerts
  - S088 consultation window every 5 min: open or close at `opensAt` and `closesAt`
  - S083 overdue-correspondence escalation daily

## Quality gates

```bash
pytest -q                         # 62 tests (SQLite by default; set TEST_DATABASE_URL for PostgreSQL)
ruff check . && ruff format --check .
bandit -q -r app
alembic upgrade head && alembic check   # migration matches the models
```

CI (`.github/workflows/ci.yml`) runs the same checks against PostgreSQL 16, plus `pip-audit`.

## Known limits

- The suite has been run on SQLite here. The migration is portable, but run it once against
  PostgreSQL (CI does this) before relying on it.
- External systems are reached only through the outbox relay. Endpoint URLs and API keys for S074,
  S203, S204, S011 and S225 must be agreed with DTI. S203 can retrieve its work queue from
  `GET /api/v1/s203/screening-cases`, post idempotent decisions to
  `POST /api/v1/s203/screening-cases/{contactId}/decision`, and inspect the case audit trail at
  `GET /api/v1/s203/screening-cases/{contactId}/activities`; these endpoints require `X-Api-Key`.
- S083 engagement sub-items (delegation, tasks, follow-ups, handoffs, approvals) are JSON arrays on the
  engagement aggregate. Move them to child tables if they need to be reported on independently.
- S084 does the same for a travel request's evidence checklist, approval chain, handoffs, issued
  documents, notifications and history — they are only ever read through the parent request.
- S084 notification retries are not an endpoint: delivery is owned by the outbox relay, and the
  workspace reloads to pick up its result.
