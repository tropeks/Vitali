/**
 * Next.js API Route: POST /api/auth/mfa-complete
 *
 * Called after a successful MFA verification. Updates access and refresh
 * cookies with the new mfa_verified=True tokens returned by Django.
 */
import { NextRequest, NextResponse } from "next/server";

const IS_PROD = process.env.NODE_ENV === "production";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.access || !body?.refresh) {
    return NextResponse.json(
      { error: "access and refresh tokens required" },
      { status: 400 }
    );
  }

  const { access, refresh } = body as { access: string; refresh: string };

  const accessMaxAge = 15 * 60;
  const refreshMaxAge = 7 * 24 * 60 * 60;

  const response = NextResponse.json({ ok: true });

  response.cookies.set("access_token", access, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: accessMaxAge,
  });

  response.cookies.set("access_token_js", access, {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: accessMaxAge,
  });

  response.cookies.set("refresh_token", refresh, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: refreshMaxAge,
  });

  return response;
}
