# Free Deployment (₹0 / $0 recurring)

This runs the whole system online, reachable from anywhere, for free —
using free tiers of four separate providers, since no single provider
gives you database + backend + cron + frontend all free forever.

**Trade-off you're accepting for ₹0**: the backend "sleeps" after ~15
minutes with no requests and takes 20-50 seconds to wake up on the next
one. Fine for a system a few people check a few times a day; noticeable if
someone hits it right after it's been idle. If that's a dealbreaker for a
client-facing deployment, the paid path in `DEPLOYMENT.md` (~₹1,500-4,000/
month total) removes this entirely — worth reconsidering once a client is
actually paying for this.

**Architecture (free version)**: `pm-scheduler` (the always-on worker) is
NOT used here — free tiers don't offer free background workers. Instead,
GitHub Actions (free) calls the new `/api/cron/*` endpoints on a schedule
over plain HTTP, which is genuinely free with no time limit for a public
repo, and has a large free-minutes allowance even for a private one (each
job run here takes a few seconds).

| Piece | Free provider | Notes |
|---|---|---|
| Database | Supabase (free tier) | 500 MB, pauses after 1 week with zero connections, wakes automatically on next connection |
| Backend API | Render (free Web Service) | Sleeps after ~15 min idle, wakes on next request |
| Scheduled jobs | GitHub Actions (free cron) | Replaces the always-on `pm-scheduler` worker |
| Frontend | Vercel (free tier) | No practical limit for this use case |

---

## 1. Database — Supabase free Postgres

1. Sign up at supabase.com, create a new project (free tier).
2. Once created, go to **Project Settings → Database → Connection string**
   and copy the URI (use the "Session pooler" connection string, not the
   direct one — Render's free tier works better through the pooler).
3. Save this — it's your `DATABASE_URL`.

## 2. Backend — Render free Web Service

1. Push this repo to GitHub.
2. Render → **New → Web Service** (not Blueprint this time, since the free
   tier doesn't support the Blueprint's worker service) → connect the repo
   → set **Root Directory** to `backend`.
3. Render auto-detects the Dockerfile. Choose the **Free** instance type.
4. Environment variables — set these in the Render dashboard:
   - `DATABASE_URL` = the Supabase connection string from step 1
   - `ENV=production`
   - `RUN_SCHEDULER_IN_API=false`
   - `TIMEZONE=Asia/Kolkata`
   - `JWT_SECRET` = any long random string
   - `CRON_SECRET` = any long random string (you'll reuse this in step 4)
   - `CORS_ALLOWED_ORIGINS` = your Vercel URL (fill in after step 3, then redeploy)
   - `APP_URL` = your Vercel URL (same, fill in after step 3, then redeploy)
   - Email provider vars (`EMAIL_PROVIDER`, `SMTP_HOST`, etc. — see
     `.env.example`) — email itself is free if you use your existing
     company email's SMTP, or Gmail's free SMTP relay.
   - `REPORT_RECIPIENTS`, `COMPANY_NAME`
   - WhatsApp vars if you have API access (`WHATSAPP_API_URL`,
     `WHATSAPP_API_TOKEN`, `ADMIN_WHATSAPP_NUMBERS`) — optional, email-only
     works fine without these.
5. Deploy. Note the resulting URL (e.g. `https://pm-backend.onrender.com`).
6. Create your first Admin account — Render free tier gives you a Shell
   tab too:
   ```bash
   python scripts/create_admin.py --email admin@yourcompany.com --name "Your Name"
   ```

## 3. Frontend — Vercel free tier

Same as the paid path — Vercel's free tier is already enough for this.
Follow **Section 2 of `DEPLOYMENT.md`** exactly (Root Directory = `frontend`,
`NEXT_PUBLIC_API_URL` and `API_URL` = your Render URL from step 2.5).

Once deployed, go back to Render and fill in `CORS_ALLOWED_ORIGINS` and
`APP_URL` with the Vercel URL, then redeploy the backend.

## 4. Scheduled jobs — GitHub Actions (replaces the paid worker)

This repo already includes `.github/workflows/pm-cron.yml`, which calls
`/api/cron/daily-reminders`, `/api/cron/monthly-report`, and
`/api/cron/sheet-freshness` on a schedule (converted to UTC in the
workflow file's comments — IST 08:00/08:30/09:00).

1. In your GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret**, add:
   - `PM_BACKEND_URL` = your Render backend URL (no trailing slash), e.g.
     `https://pm-backend.onrender.com`
   - `PM_CRON_SECRET` = the exact same value you set as `CRON_SECRET` on
     Render in step 2.4
2. That's it — GitHub will run the workflow on schedule automatically.
   Nothing to install, no server to maintain.
3. To test it right now instead of waiting for the schedule: go to your
   repo's **Actions** tab → "PM System Cron Jobs" → **Run workflow**
   (this uses the `workflow_dispatch` trigger already in the file) → pick
   a job → Run. Check the run's logs for the curl response.

**Cold-start note**: the first cron call after the backend has been idle
will take longer (Render waking up) — the workflow's `--max-time 90`
already accounts for this, but if you ever see it time out, bump that
number higher.

## 5. Post-deploy checklist

Same as the paid path — see the checklist at the bottom of `DEPLOYMENT.md`.
Steps 1-3 (login, import, manual freshness trigger) work identically here;
for step 4 (daily reminder), use the GitHub Actions manual trigger from
section 4.3 above instead of waiting for `scheduler_main.py`, since that
process doesn't exist in this setup.

## When to move off the free path

Move to the paid setup in `DEPLOYMENT.md` when any of these start to
matter:
- The 20-50s cold-start wake becomes annoying for the people using it daily.
- Supabase's free 500 MB fills up (unlikely for this data volume for a
  long time, but worth knowing the ceiling exists).
- You're delivering this to a paying client and want it to feel
  production-grade rather than "the free version."
