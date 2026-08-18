/**
 * Next.js API Route: POST /api/auth/mfa-complete
 *
 * Called after a successful MFA verification. Updates access and refresh
 * cookies with the new mfa_verified=True tokens returned by Django.
 *
 * SECURITY (Onda 0 / item 0.6-frontend): the request body is client-supplied
 * and MUST NOT be trusted blindly — a forged {access, refresh} pair here would
 * let anyone mint an arbitrary session. Before writing any cookie we round-trip
 * the access token to Django's /api/v1/me: only a token whose signature Django
 * itself accepts can reach this point. The whole point of this route is also to
 * confirm the *second factor* was actually completed, so we additionally read
 * the mfa_verified claim out of the token payload — see the comment on
 * decodeJwtPayload for why that read is NOT itself a trust boundary.
 */
import { NextRequest, NextResponse } from "next/server";

import { djangoApiBaseUrl } from "@/lib/server/django-api";

const IS_PROD = process.env.NODE_ENV === "production";

const ACCESS_MAX_AGE = 15 * 60;
const REFRESH_MAX_AGE = 7 * 24 * 60 * 60;

/**
 * Decodes the middle segment of a JWT to read its claims, WITHOUT verifying
 * the signature. This is intentionally NOT an authentication check — anyone
 * can forge a JWT-shaped string with any claims they like. It only tells us
 * what a token *claims* to be. Trust that the token is genuine comes solely
 * from the round-trip to Django (`/api/v1/me`) in the caller below, which
 * validates the signature server-side and rejects it if it's invalid.
 *
 * We use this purely to read the `mfa_verified` claim, because Django's /me
 * endpoint does not echo it back (S-062's MFARequiredMiddleware only enforces
 * that claim for staff/superuser/admin/medico/dentista — regular users pass
 * /me regardless of it), so a round-trip success alone can't tell us whether
 * MFA was actually completed.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = Buffer.from(parts[1], "base64url").toString("utf8");
    const parsed: unknown = JSON.parse(json);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

function forwardedHostFrom(req: NextRequest): string {
  const rawHost = req.headers.get("host") ?? "localhost";
  return rawHost.split(":")[0];
}

// Generic 401 for every rejection path (forged token, expired token, backend
// down, missing mfa_verified claim) — the response body must not let a caller
// distinguish *why* the session wasn't established.
function rejected() {
  return NextResponse.json({ error: "Sessão inválida." }, { status: 401 });
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.access || !body?.refresh) {
    return NextResponse.json(
      { error: "access and refresh tokens required" },
      { status: 400 }
    );
  }

  const { access, refresh } = body as { access: string; refresh: string };

  const claims = decodeJwtPayload(access);
  if (!claims || claims.mfa_verified !== true) {
    return rejected();
  }

  const forwardedHost = forwardedHostFrom(req);

  let meResp: Response;
  try {
    meResp = await fetch(`${djangoApiBaseUrl()}/api/v1/me`, {
      method: "GET",
      headers: {
        "X-Forwarded-Host": forwardedHost,
        "X-Forwarded-Proto": "https",
        Authorization: `Bearer ${access}`,
      },
      cache: "no-store",
    });
  } catch {
    return rejected();
  }

  if (!meResp.ok) {
    return rejected();
  }

  // Consume the body so the connection is released; the DTO itself isn't
  // needed here (unlike /api/auth/login and /set-password, this route never
  // rewrote vitali_user, and item 0.6 keeps that behavior unchanged).
  await meResp.json().catch(() => null);

  const response = NextResponse.json({ ok: true });

  response.cookies.set("access_token", access, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });

  response.cookies.set("access_token_js", access, {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });

  response.cookies.set("refresh_token", refresh, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_MAX_AGE,
  });

  return response;
}
