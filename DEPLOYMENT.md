# Deployment Guide

This gets the system running unattended in production — i.e. the daily
08:00 reminder job and the monthly report job actually fire on their own,
which they never will on a laptop that's turned off overnight.

Architecture: **3 pieces**, same as `docker-compose.yml` locally:

| Piece | Local (docker-compose) | Production |
|---|---|---|
| Backend API | `backend` service | Render Web Service (`pm-backend`) |
| Scheduler worker | `scheduler` service | Render Background Worker (`pm-scheduler`) |
| Database | `db` service | Render Managed Postgres |
| Frontend | `frontend` service | Vercel |

The scheduler is a **separate always-on process** from the API. This
matters: if you only deploy the API, nothing will ever send a reminder —
there is no cron running inside the request/response web service.

---

## 1. Backend + scheduler + database → Render

1. Push this repo to GitHub (if it isn't already).
2. In the Render dashboard: **New → Blueprint**, point it at the repo.
   Render reads `render.yaml` at the repo root and provisions:
   - `pm-system-db` (managed Postgres)
   - `pm-backend` (web service, runs `alembic upgrade head` then `uvicorn`
     on container start — see `backend/Dockerfile`)
   - `pm-scheduler` (background worker, runs `scheduler_main.py`)
3. `render.yaml` deliberately leaves secrets (SMTP/Gmail/M365/WhatsApp
   credentials, `REPORT_RECIPIENTS`, `COMPANY_NAME`, `CORS_ALLOWED_ORIGINS`,
   `APP_URL`) as `sync: false` so nothing sensitive is committed. After the
   first deploy, go to each service's **Environment** tab in Render and
   fill these in. **Fill them in on BOTH `pm-backend` and `pm-scheduler`** —
   the scheduler is the process that actually sends the emails/WhatsApp
   messages for the daily/monthly/freshness jobs, so it needs the same
   notification credentials as the API.
4. Keep `pm-scheduler`'s instance count at **1**. The jobs are idempotent
   (duplicate sends are guarded against), but it's designed as a single
   always-on worker, not a scaled pool.
5. Storage: `render.yaml` defaults `STORAGE_BACKEND=s3` for PM-completion
   photo/PDF attachments and Excel uploads, since Render's local disk isn't
   guaranteed to persist across deploys on all plans. Use S3, Cloudflare R2,
   or Render's own disk add-on — fill in `S3_BUCKET` / `S3_ENDPOINT_URL` /
   `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` accordingly. If you'd rather
   start simpler, set `STORAGE_BACKEND=local` and attach a Render persistent
   disk to `pm-backend` at `LOCAL_STORAGE_DIR` — fine as long as you never
   scale `pm-backend` past 1 replica.
6. Once deployed, note the `pm-backend` URL (e.g.
   `https://pm-backend.onrender.com`) — you'll need it for the frontend's
   `NEXT_PUBLIC_API_URL` and `API_URL` in step 2.

## 2. Frontend → Vercel

1. In Vercel: **Add New → Project**, import the same GitHub repo.
2. Set **Root Directory** to `frontend` (this is a monorepo — the backend
   lives in a sibling folder). Vercel auto-detects Next.js from there;
   `frontend/vercel.json` pins the build/install commands explicitly.
3. Environment variables (Vercel dashboard → Settings → Environment
   Variables):
   - `NEXT_PUBLIC_API_URL` = your Render backend URL (from step 1.6) — used
     client-side for direct calls.
   - `API_URL` = same Render backend URL — used server-side by the Next.js
     API routes that proxy to FastAPI (`frontend/app/api/proxy`). Do **not**
     prefix this one with `NEXT_PUBLIC_`, it's intentionally server-only.
4. Deploy. Note the resulting Vercel URL (e.g. `https://pm.vercel.app`).
5. Go back to Render → `pm-backend` → Environment, and set:
   - `CORS_ALLOWED_ORIGINS` = your Vercel URL (comma-separated if you have
     more than one, e.g. a staging + production domain).
   - `APP_URL` = your Vercel URL — this is what the "Mark PM Complete"
     links in reminder emails/WhatsApp messages are built from
     (`app/notifications/templates.py`), so it must be the real
     user-facing domain, not `localhost`.
6. Redeploy `pm-backend` after changing those two (env var changes on
   Render require a redeploy to take effect for a running service).

## 3. Custom domain (optional but recommended for a "professional" deployment)

- Point `pm.yourcompany.com` (or similar) at the Vercel project (Vercel →
  Domains).
- Point `api.yourcompany.com` at the Render `pm-backend` service (Render →
  Settings → Custom Domain).
- Update `APP_URL`, `NEXT_PUBLIC_API_URL`, `API_URL`, and
  `CORS_ALLOWED_ORIGINS` to the real domains once both are live, and
  redeploy both services.

## 4. Post-deploy checklist

Run through this once, in order, before treating the system as live:

1. SSH/exec into the `pm-backend` service (Render → Shell tab, or `render
   ssh pm-backend` with the CLI) and run:
   ```bash
   python scripts/create_admin.py --email admin@yourcompany.com --name "Your Name"
   ```
   This is the only way to create the first account — employee creation is
   Admin-only through the API by design. Re-running it later with the same
   email resets that password if needed.
2. Log in at the Vercel URL with that Admin account.
2. **Admin → Settings**: confirm the panel loads (this was broken in the
   original build — the router existed but was never registered; fixed as
   part of this update) and the new `sheet_freshness_days` /
   `sheet_freshness_month_end_day` settings are visible and tunable.
3. **Import**: upload your real PM planning workbook in commit mode. Check
   the machine/plan counts match what you expect.
4. **Trigger a manual freshness check**: `POST
   /api/admin/data-freshness/check-now` (Admin-only) — confirms email/
   WhatsApp credentials actually work end-to-end without waiting for the
   real cron or a real staleness condition. Expect
   `{"staleness_alert_sent": true, ...}` on a fresh database with no prior
   import, since "never imported" always counts as stale.
5. Manually complete one PM plan via the frontend, and confirm it stops
   appearing in the reminder queries.
6. Wait for (or, in a staging environment, manually invoke)
   `run_daily_reminder_job` — confirm a real email/WhatsApp reminder
   arrives with the correct machine name, date, and a working "Mark PM
   Complete" link pointing at your real `APP_URL`.
7. At month-end, confirm the monthly report email arrives with both PDF
   and Excel attachments and the numbers look right against what you know
   was actually completed.
8. Set up `scripts/backup.sh` on a real cron (see the README's Backup &
   Restore section) pointed at storage separate from the Render Postgres
   instance itself.

## Notes

- Nothing here is tied to Render/Vercel specifically — the Dockerfiles are
  plain, so any container host (Railway, Fly.io, your own VPS with Docker
  Compose) works too. Render + Vercel is the path of least setup effort for
  a small-to-mid deployment.
- `ENV=production` on the backend disables the dev-only
  `Base.metadata.create_all()` fallback — the Dockerfile's `alembic upgrade
  head` on container start is what actually creates/migrates the schema in
  production. Don't skip that step if you ever run the backend without the
  Docker image's default `CMD`.
