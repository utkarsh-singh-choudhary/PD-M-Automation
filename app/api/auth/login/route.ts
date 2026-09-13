import { NextRequest, NextResponse } from "next/server";

// BFF login: the browser never sees the JWT or refresh token. This route
// is the only place that talks to FastAPI's /api/auth/login; it takes the
// access_token + refresh_token from the response and stores BOTH in
// HttpOnly cookies, so client-side JS (and therefore any XSS payload)
// cannot read either. `pm_user` carries only non-sensitive display data
// (name/role/id) and stays a normal cookie so the UI can render without an
// extra round trip.
//
// pm_token now expires in line with the backend's shortened access-token
// lifetime (JWT_EXPIRE_MINUTES, default 30min) rather than the old 8h -
// the 8h+ session is now carried by pm_refresh instead, which the proxy
// route uses to silently mint a new access token when the old one expires
// (see app/api/proxy/[...path]/route.ts). This is the "short-lived access
// token + longer-lived, revocable refresh token" hardening from the
// production review's "JWT session security" item.
const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const IS_PROD = process.env.NODE_ENV === "production";
const ACCESS_TOKEN_MAX_AGE = 60 * 30; // 30 min, matches backend default
const REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 14; // 14 days, matches backend default

export async function POST(req: NextRequest) {
  const body = await req.text(); // already x-www-form-urlencoded from the client

  const upstream = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  const data = await upstream.json().catch(() => null);

  if (!upstream.ok) {
    return NextResponse.json(data ?? { detail: "Login failed" }, { status: upstream.status });
  }

  const res = NextResponse.json({
    employee_id: data.employee_id,
    name: data.name,
    role: data.role,
  });

  res.cookies.set("pm_token", data.access_token, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_TOKEN_MAX_AGE,
  });

  res.cookies.set("pm_refresh", data.refresh_token, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/", // scoped to the whole app since both /api/proxy and /api/auth/logout need it
    maxAge: REFRESH_TOKEN_MAX_AGE,
  });

  res.cookies.set(
    "pm_user",
    JSON.stringify({ employee_id: data.employee_id, name: data.name, role: data.role }),
    { httpOnly: false, secure: IS_PROD, sameSite: "lax", path: "/", maxAge: REFRESH_TOKEN_MAX_AGE }
  );

  // CSRF double-submit token (P1: "CSRF defense appropriate to deployment
  // model"). pm_token/pm_refresh are `sameSite: "lax"`, which already
  // blocks the vast majority of cross-site request forgery - but "lax"
  // still allows *some* top-level cross-site navigations to carry cookies
  // in certain browsers/edge cases, and this is a role-based industrial
  // system where a forged "cancel this PM" or "change this setting" POST
  // is a meaningful risk. This token is deliberately NOT HttpOnly (the
  // client needs to read it to echo it back as a header) - it's not a
  // secret on its own, it only proves the request originated from JS
  // running on this origin, which a cross-site form/img/script tag
  // cannot do.
  const csrfToken = crypto.randomUUID();
  res.cookies.set("pm_csrf", csrfToken, {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_TOKEN_MAX_AGE,
  });

  return res;
}
