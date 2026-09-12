from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://pm_user:pm_password@localhost:5432/pm_system"

    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    # Shortened from 480 (8h) - a bearer access token that leaks is valid
    # until expiry with no revocation, so it should be short-lived; the
    # refresh-token flow (see core/security.py, routers/auth.py) is what
    # actually keeps a plant-floor shift logged in for 8+ hours without
    # re-entering a password, while making the *revocable* session the
    # long-lived part instead of the bearer token (High Priority: "JWT
    # session security can be improved").
    JWT_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    TIMEZONE: str = "Asia/Kolkata"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    ENV: str = "development"

    # False in production: the scheduler runs in its own process
    # (scheduler_main.py / the `pm-scheduler` service), not inside every
    # API replica. See main.py's lifespan handler for why.
    RUN_SCHEDULER_IN_API: bool = False

    # Comma-separated list of allowed origins for CORS. In production this
    # MUST be set to the real dashboard origin(s), e.g.
    # "https://pm.yourcompany.com". Falls back to APP_URL if unset so a
    # single-origin deployment works without extra config; never defaults
    # to "*".
    CORS_ALLOWED_ORIGINS: str = ""

    @property
    def cors_origins(self) -> list[str]:
        raw = self.CORS_ALLOWED_ORIGINS.strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return [self.APP_URL]

    EMAIL_PROVIDER: str = "smtp_generic"  # m365 | gmail | smtp_generic
    NOTIFICATIONS_ENABLED: bool = True

    MS365_TENANT_ID: str = ""
    MS365_CLIENT_ID: str = ""
    MS365_CLIENT_SECRET: str = ""
    MS365_SENDER_ADDRESS: str = ""

    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REFRESH_TOKEN: str = ""
    GMAIL_SENDER_ADDRESS: str = ""

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""

    WHATSAPP_API_URL: str = ""
    WHATSAPP_API_TOKEN: str = ""

    # Comma-separated E.164 numbers (e.g. "+9198xxxxxxx,+9199xxxxxxx") that
    # should also get the "planning sheet not updated" WhatsApp alert.
    # Optional - the alert always goes to REPORT_RECIPIENTS by email
    # regardless of whether this is set.
    ADMIN_WHATSAPP_NUMBERS: str = ""

    # Comma-separated list of management emails for the monthly report
    # (and, since Phase 5, the sheet-freshness alert below).
    REPORT_RECIPIENTS: str = ""

    # Shared secret for POST /api/cron/* endpoints - lets an external
    # scheduler (e.g. a free GitHub Actions cron workflow, used when
    # there's no budget for an always-on background worker) trigger the
    # daily/monthly/freshness jobs over HTTP instead of running
    # scheduler_main.py as a persistent process. Leave blank to disable
    # these endpoints entirely (they 403 if CRON_SECRET is unset).
    CRON_SECRET: str = ""

    # Shown in the branded HTML email header. Falls back to a generic
    # label in templates.py if left blank.
    COMPANY_NAME: str = ""

    # --- Object storage (attachments + Excel uploads) ---------------------
    # STORAGE_BACKEND: "local" (dev default, persistent volume - NOT /tmp)
    # or "s3" (AWS S3 / Cloudflare R2 / MinIO, all speak the same S3 API).
    # For R2 or MinIO, set S3_ENDPOINT_URL to their endpoint; leave blank
    # for real AWS S3.
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_DIR: str = "/data/pm_storage"  # mount a real volume here in prod, never /tmp

    S3_BUCKET: str = ""
    S3_REGION: str = "auto"
    S3_ENDPOINT_URL: str = ""  # e.g. https://<accountid>.r2.cloudflarestorage.com, or http://minio:9000
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PRESIGNED_URL_TTL_SECONDS: int = 300

    # --- Malware scanning (High Priority: "File upload still needs
    # malware scanning") ---------------------------------------------------
    # Off by default so a fresh install doesn't silently 500 on every
    # upload before ClamAV is set up. Set CLAMAV_ENABLED=true once a clamd
    # daemon is reachable (see app/core/malware_scan.py for the fail-open
    # behavior and why it's logged loudly when misconfigured).
    CLAMAV_ENABLED: bool = False
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310
    CLAMAV_UNIX_SOCKET: str = ""  # if set, takes priority over host/port

    # Locked business rule: week-code -> calendar date convention
    # W1 = 1-7, W2 = 8-14, W3 = 15-21, W4 = 22-28, W5 = 29-end of month
    WEEK_BAND_SIZE_DAYS: int = 7


settings = Settings()
