# Preventive Maintenance Automation System — Phase 1

## What's implemented (Phase 1 + core of Phase 2)

- PostgreSQL schema: Machine, Employee, MachineResponsibility, PMPlan, PMActual,
  NotificationLog, AuditLog, ImportBatch (`app/models/models.py`)
- Excel importer supporting all 3 plan-encoding formats found in your workbook:
  - `EXACT_DATE` (PD Plan, FY23-24)
  - `DAY_OF_MONTH` (PD Plan-, Auto line)
  - `WEEK_CODE` W1–W5 (PM Plan-26-27), converted to calendar dates using the
    **locked convention**: W1=1–7, W2=8–14, W3=15–21, W4=22–28, W5=29–end of month.
  - Unknown/unparseable cells are recorded as warnings, never guessed.
  - Validated directly against your uploaded workbook (see test run below).
- Import service with preview (no writes) vs commit mode, duplicate prevention
  via a DB unique constraint, and full source traceability (file/sheet/cell).
- Notification abstraction (`app/notifications/`) with three interchangeable
  email providers already wired in:
  - **Microsoft 365 / Outlook** (Graph API, `m365_provider.py`)
  - **Gmail** (Gmail API OAuth2, `gmail_provider.py`)
  - **Generic SMTP** fallback (works with either, via app password/SMTP AUTH)
  - Switch active provider anytime via `EMAIL_PROVIDER` in `.env` — no business
    logic changes needed. Both can be added independently, at your own pace.
- Reminder/escalation job (`app/jobs/reminder_jobs.py`) using idempotency keys
  (`pm_id + type + date`) so a scheduler restart can never double-send.
- REST API: machines, PM plans (list/upcoming/overdue/complete), Excel import
  (upload/preview/commit), health checks.
- APScheduler running the daily reminder job at 08:00 Asia/Kolkata.

- Next.js + TypeScript + Tailwind dashboard (`frontend/`): KPI cards, upcoming/
  overdue tables, machines list, and the full 7-step Excel import wizard
  (upload → select sheet → detect → preview → validate → import → summary),
  talking to the backend via `NEXT_PUBLIC_API_URL`. Builds clean with
  `next build` (verified).

- **Auth/RBAC**: JWT login (`POST /api/auth/login`), bcrypt password hashing,
  `require_roles(...)` dependency protecting PM completion, Excel import,
  employee admin, and report endpoints per the 5 roles in the spec (Admin,
  Manager, Supervisor, Technician, Viewer).
- **Audit logging**: `record_audit()` helper wired into login, PM completion,
  Excel upload/commit, employee creation, and report generation — answers
  "who changed this and when" via `GET /api/audit-logs` (Admin/Manager only).
- **Monthly report engine** (`app/reports/`): computes Plan/Actual/Pending/
  Overdue/Completion-rate/On-time-rate, machine-wise, location-wise and
  employee-wise breakdowns, and an overdue list — exactly per spec section 14.
  Renders to both **PDF** (reportlab) and **Excel** (openpyxl) via
  `GET/POST /api/reports/monthly` and `/api/reports/monthly/generate`.
- **Monthly scheduled job**: runs 1st of each month at 09:00 IST, generates
  the previous month's report and emails a summary to `REPORT_RECIPIENTS`
  (comma-separated in `.env`) via whichever email provider is active.

## Next phases

- SMS provider (WhatsApp and email are implemented; see "Notification provider setup" below)

## Phase 5 additions 

- **HTML email + short WhatsApp templates**: every reminder/escalation now
  renders as a branded HTML email (with plain-text fallback) and a
  shortened WhatsApp-friendly version, both including a direct "Mark PM
  Complete" link so recipients don't have to open the app to find the
  right machine (`app/notifications/templates.py`).
- **Sheet-freshness alerts**: a new daily-checked, weekly/monthly-idempotent
  job (`app/jobs/data_freshness_job.py`) alerts admins/planners — not
  technicians — if the PM planning Excel sheet itself hasn't been
  re-uploaded recently (staleness threshold) or hasn't been re-uploaded yet
  this calendar month past a configurable day-of-month. Both thresholds are
  admin-tunable via the same `/api/admin/settings` panel as the existing
  reminder/escalation settings. Manually testable via `POST
  /api/admin/data-freshness/check-now`.
- **Fixed**: `admin_settings` router was imported in `app/main.py` but never
  registered with `app.include_router()` — the `/admin` settings panel
  would 404 on every call. Now wired in.
- **Deployment**: `render.yaml` (backend API + dedicated scheduler worker +
  managed Postgres) and `frontend/vercel.json`, plus `DEPLOYMENT.md` with a
  step-by-step walkthrough and a post-deploy verification checklist. See
  that file for the full guide.
- **Free deployment path**: `app/routers/cron.py` exposes
  `/api/cron/daily-reminders`, `/api/cron/monthly-report`, and
  `/api/cron/sheet-freshness`, secret-protected via `CRON_SECRET`, so a
  free GitHub Actions scheduled workflow
  (`.github/workflows/pm-cron.yml`) can trigger the same jobs
  `scheduler_main.py` runs, without needing a paid always-on worker. See
  `FREE_DEPLOYMENT.md`.
- **First-run fix**: `backend/scripts/create_admin.py` creates or
  password-resets the first Admin account — previously there was no way to
  create the very first login, since employee creation is Admin-only
  through the API.
- **Dependency fix**: pinned `bcrypt==4.0.1` in `requirements.txt` — newer
  bcrypt releases break passlib 1.7.4's hashing/verification entirely,
  which would have made every login fail on a fresh install.

## Deployment

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full Render (backend +
scheduler + Postgres) + Vercel (frontend) walkthrough, including which
environment variables need to be filled in and a post-deploy checklist to
verify reminders/reports actually send before treating the system as live.

**No budget yet?** See [`FREE_DEPLOYMENT.md`](./FREE_DEPLOYMENT.md) for a
₹0/month path using Supabase's free Postgres, Render's free web service,
Vercel's free tier, and a free GitHub Actions cron in place of the paid
always-on worker — same features, with a cold-start trade-off.

## Phase 4 additions 

- **Alembic migrations**: `backend/alembic/versions/0001_initial.py` creates the
  full schema by hand (matches `app/models/models.py`). `Base.metadata.create_all`
  now only runs when `ENV=development`; everywhere else, run
  `alembic upgrade head` as a deploy step (the Docker image does this
  automatically on container start).
- **Excel sync/diff**: `POST /api/import/excel/preview` now does a real
  add/changed/removed diff (previously preview mode always reported every row
  as "created" — fixed). Rows removed from the re-uploaded sheet are flagged
  and, on commit, cancelled rather than hard-deleted (a plan with a recorded
  completion is left untouched either way).
- **Frontend login + role-aware UI**: `/login`, a cookie-based JWT session
  (`frontend/lib/auth.ts`), route protection via `middleware.ts`, and a
  role-filtered sidebar (Import/Audit/Admin links only show for the roles
  that can use them).
- **PDF/Excel attached to report emails**: `EmailAttachment` support added to
  all three providers (SMTP, Gmail, M365); the monthly job now attaches the
  real PDF + Excel files instead of a text-only summary.
- **Attachment/photo upload on PM completion**: `POST /api/pm/{id}/complete`
  is now `multipart/form-data` and accepts an optional `attachment` file
  (image or PDF, 15MB cap); `GET /api/pm/{id}/attachment` retrieves it. A
  simple completion form lives at `/pm/[id]/complete` in the frontend.
- **Admin settings panel**: new `app_settings` table + `/api/admin/settings`
  (Admin only) exposes `reminder_days_before`, `due_tomorrow_days_before`,
  `escalation_thresholds`, and the week→date convention
  (`week_band_size_days`, `week_start_offset_days`) as DB-backed, live-tunable
  values — no code deploy needed. Frontend page at `/admin`.

## Local setup (Windows PowerShell)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env with your DB and email provider credentials
alembic upgrade head
uvicorn app.main:app --reload
```

Database via Docker:
```powershell
docker compose up -d db
```

Frontend (in a second terminal):
```powershell
cd frontend
npm install
npm run dev
```
Then open http://localhost:3000 — it talks to the backend at
`NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Docker (full stack)

```bash
docker compose up --build
```

## First login: creating your first Admin account

Employee creation is Admin-only through the API, which is correct for
ongoing use but leaves no way to create the very first account. Use the
bootstrap script instead:

```bash
cd backend
python scripts/create_admin.py --email admin@yourcompany.com --name "Your Name"
```

It prompts for a password (not passed as an argument, so it never lands in
shell history), hashes it the same way normal login does, and creates an
Admin employee row. Re-running it with the same `--email` resets that
account's password instead of creating a duplicate — so it also works as a
password-reset tool later, not just for the first account.

In Docker: `docker compose exec backend python scripts/create_admin.py --email admin@yourcompany.com --name "Your Name"`


## Testing the importer against your real file

```bash
python -c "
from app.importer.excel_importer import load_workbook_from_path, parse_pm_sheet
wb = load_workbook_from_path('path/to/your.xlsx')
result = parse_pm_sheet(wb['PM Plan-26-27'], 'PM Plan-26-27', '26-27')
print(len(result.rows), 'machines parsed,', len(result.warnings), 'warnings')
"
```
This was run against your uploaded file: **90 machine rows parsed, 0 warnings,
0 errors** for the FY26-27 week-code sheet.

## Notification provider setup

**Microsoft 365**: register an Azure AD app, grant `Mail.Send` (application,
admin-consented), fill `MS365_TENANT_ID/CLIENT_ID/CLIENT_SECRET/SENDER_ADDRESS`.

**Gmail**: enable the Gmail API in a Google Cloud project, create an OAuth2
client, run a one-time consent flow to get a refresh token, fill
`GMAIL_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN/SENDER_ADDRESS`.

Set `EMAIL_PROVIDER=m365` or `gmail` or `smtp_generic` in `.env` to pick which
is active. You can add one now and the other later without any code changes.

**WhatsApp**: works with Meta's own WhatsApp Business Cloud API directly, or
any compatible BSP (Twilio, Gupshup, etc. — a BSP is usually faster to get
approved and live than going direct to Meta). Fill `WHATSAPP_API_URL` (the
send-message endpoint) and `WHATSAPP_API_TOKEN` in `.env`. Per-employee,
WhatsApp is preferred over email automatically when an employee has
`notification_whatsapp_enabled=true` and a phone number set
(`app/notifications/notification_service.py:pick_channel_for_employee`) — if
a WhatsApp send fails, it falls back to email rather than failing silently.
Optionally set `ADMIN_WHATSAPP_NUMBERS` (comma-separated E.164 numbers) to
also receive the sheet-not-updated alert on WhatsApp, in addition to
`REPORT_RECIPIENTS` by email.

## Running the automated tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

`tests/test_excel_importer.py` covers the importer's edge cases (mixed
date formats, week codes, day-of-month clamping/overflow, copy-forward
P==A detection, footer-row cutoff, the review-queue flags, and the
near-duplicate normalization rule) as pure-function tests - no Postgres
needed. Run this before pointing a new build at production data, and add
a case here any time a new "weird real spreadsheet" pattern shows up.

## Timezone handling

Business-logic "what day is it" checks (daily reminders, overdue/upcoming
queries, monthly report period) go through `app/core/timeutils.py`
(`today_local()` / `now_local()`), which is explicitly `Asia/Kolkata`-aware
via `settings.TIMEZONE` - not `date.today()`/`datetime.now()`, which use
whatever timezone the server process happens to be in (UTC in most
containers). Without this, a server on UTC would compute "today" a day
behind IST for roughly 18:30–23:59 UTC every day, silently shifting
reminders/escalations by a day for that window. `datetime.utcnow()` is
still used (correctly) for pure timestamp columns - `created_at`,
`sent_at`, JWT expiry - where UTC is the right choice and there's no
"business day" boundary involved.

## Backup & restore

`scripts/backup.sh` runs a `pg_dump -Fc` (compressed, restorable with
`pg_restore`) against the `db` container, verifies the dump is non-empty
before declaring success, and prunes dumps older than `RETENTION_DAYS`
(default 30). Run it from the host via cron, not from inside
docker-compose - a backup shouldn't live on the same machine/volume it's
protecting against by default; point `BACKUP_DIR` at separate storage
(NAS, S3-mounted path, etc).

```bash
BACKUP_DIR=/mnt/backups/pm_system ./scripts/backup.sh
# suggested cron: 0 2 * * *  (2am IST, clear of the 8am reminder job)
```

`scripts/restore.sh` restores a dump, but always into a scratch database
first:

```bash
./scripts/restore.sh backups/pm_system_20260911_020000.dump pm_system_restore_test
# inspect pm_system_restore_test - row counts, spot-check a few machines/plans
./scripts/restore.sh backups/pm_system_20260911_020000.dump pm_system   # only once verified
```

It requires typing the target database name to confirm before it drops
anything, since a restore is destructive by nature.

This covers backup/restore mechanics; it does not replace testing an
actual disaster-recovery drill (kill the `db` volume, restore from the
latest dump, confirm the app comes back clean) before this becomes the
system of record.



- Frontend → Vercel, Backend → Render/Railway or your own container host,
  PostgreSQL → managed Postgres. Nothing here is tied to a single provider.
- Alembic migrations are now real (see Phase 4 notes above) — just run
  `alembic upgrade head` against production before first deploy.
- Tighten CORS `allow_origins` in `app/main.py` to your real `APP_URL`.
