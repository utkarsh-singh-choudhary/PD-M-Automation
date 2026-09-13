"use client";

// The JWT itself now lives only in an HttpOnly cookie (`pm_token`), set by
// the server route /api/auth/login - this file never sees or stores the
// token. `pm_user` is a plain (non-HttpOnly) cookie holding only
// non-sensitive display fields (name/role/id) so the UI can render without
// an extra request; it carries no auth power on its own. Every actual API
// call goes through /api/proxy/*, which reads pm_token server-side.
const USER_COOKIE = "pm_user";

export type Role = "ADMIN" | "MANAGER" | "SUPERVISOR" | "TECHNICIAN" | "VIEWER";

export type AuthUser = {
  employee_id: string;
  name: string;
  role: Role;
};

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function getUser(): AuthUser | null {
  if (typeof document === "undefined") return null;
  const raw = getCookie(USER_COOKIE);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
  window.location.href = "/login";
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.detail || "Invalid email or password");
  }
  return data as AuthUser;
}

/** Which roles can see which nav sections / take which actions. */
export const ROLE_CAN = {
  viewImport: (role?: Role) => role === "ADMIN" || role === "MANAGER",
  viewAdmin: (role?: Role) => role === "ADMIN",
  viewAudit: (role?: Role) => role === "ADMIN" || role === "MANAGER",
  completePM: (role?: Role) =>
    role === "TECHNICIAN" || role === "SUPERVISOR" || role === "MANAGER" || role === "ADMIN",
};
