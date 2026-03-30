/**
 * Next.js API Route: POST /api/auth/login
 *
 * Proxies credentials to Django, then sets httpOnly cookies for
 * access_token and refresh_token, and a readable cookie for UserDTO.
 */
import { NextRequest, NextResponse } from "next/server";

const DJANGO_API = process.env.DJANGO_API_URL ?? "http://localhost:8000";
const IS_PROD = process.env.NODE_ENV === "production";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.email || !body?.password) {
    return NextResponse.json(
      { error: { code: "VALIDATION_ERROR", message: "email e password obrigatórios." } },
      { status: 400 }
    );
  }

  let djangoResp: Response;
  try {
    djangoResp = await fetch(`${DJANGO_API}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: body.email, password: body.password }),
    });
  } catch {
    return NextResponse.json(
      { error: { code: "BACKEND_UNAVAILABLE", message: "Serviço indisponível." } },
      { status: 503 }
    );
  }

  const data = await djangoResp.json();

  if (!djangoResp.ok) {
    return NextResponse.json(data, { status: djangoResp.status });
  }

  const { access, refresh, user } = data as {
    access: string;
    refresh: string;
    user: Record<string, unknown>;
  };

  // Access token expires in 15 min; refresh in 7 days
  const accessMaxAge = 15 * 60;
  const refreshMaxAge = 7 * 24 * 60 * 60;

  const response = NextResponse.json({ user });

  response.cookies.set("access_token", access, {
    httpOnly: true,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: accessMaxAge,
  });

  // Non-httpOnly mirror so client JS can attach Bearer tokens to direct API calls.
  // Same value and expiry as the httpOnly cookie above.
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

  // Non-httpOnly cookie so client JS can read user info
  response.cookies.set("vitali_user", JSON.stringify(user), {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: refreshMaxAge,
  });

  return response;
}
