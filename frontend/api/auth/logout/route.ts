import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const accessToken = req.cookies.get("pm_token")?.value;
  const refreshToken = req.cookies.get("pm_refresh")?.value;

  // Best-effort server-side revocation: actually end the session in the
  // backend's refresh_tokens table, not just clear the browser's cookies
  // (High Priority: "JWT session security can be improved" - previously
  // logout was purely client-side, so a stolen token/cookie stayed valid
  // until natural expiry). Never let a backend hiccup block the user from
  // clearing their local session either way.
  if (accessToken && refreshToken) {
    try {
      await fetch(`${API_URL}/api/auth/logout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Ignore - cookies are cleared below regardless, so the browser
      // session ends either way; worst case the server-side row expires
      // naturally at REFRESH_TOKEN_EXPIRE_DAYS instead of being revoked
      // immediately.
    }
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set("pm_token", "", { path: "/", maxAge: 0 });
  res.cookies.set("pm_refresh", "", { path: "/", maxAge: 0 });
  res.cookies.set("pm_user", "", { path: "/", maxAge: 0 });
  res.cookies.set("pm_csrf", "", { path: "/", maxAge: 0 });
  return res;
}
