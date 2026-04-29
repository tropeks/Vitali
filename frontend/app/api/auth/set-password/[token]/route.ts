/**
 * Next.js API Route: POST /api/auth/set-password/:token
 *
 * Completes the invitation password flow through Django, then creates the
 * same browser session cookies as /api/auth/login. The client page must not
 * call /api/v1/auth/set-password directly because the Next middleware uses
 * cookies, not localStorage, to recognize an authenticated user.
 */
import { NextRequest, NextResponse } from "next/server";

const DJANGO_API =
  process.env.DJANGO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";
const IS_PROD = process.env.NODE_ENV === "production";

const ACCESS_MAX_AGE = 15 * 60;
const REFRESH_MAX_AGE = 7 * 24 * 60 * 60;

type SetPasswordPayload = {
  access?: string;
  refresh?: string;
  error?: unknown;
};

type UserDTO = Record<string, unknown>;

function forwardedHostFrom(req: NextRequest): string {
  const rawHost = req.headers.get("host") ?? "localhost";
  return rawHost.split(":")[0];
}

function setSessionCookies(response: NextResponse, access: string, refresh: string, user: UserDTO) {
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

  response.cookies.set("vitali_user", JSON.stringify(user), {
    httpOnly: false,
    secure: IS_PROD,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_MAX_AGE,
  });
}

export async function POST(req: NextRequest, { params }: { params: { token: string } }) {
  const body = await req.json().catch(() => null);
  if (!body?.password) {
    return NextResponse.json(
      { error: { code: "VALIDATION_ERROR", message: "password obrigatorio." } },
      { status: 400 }
    );
  }

  const forwardedHost = forwardedHostFrom(req);

  let djangoResp: Response;
  try {
    djangoResp = await fetch(`${DJANGO_API}/api/v1/auth/set-password/${encodeURIComponent(params.token)}/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-Host": forwardedHost,
      },
      body: JSON.stringify({ password: body.password }),
    });
  } catch {
    return NextResponse.json(
      { error: { code: "BACKEND_UNAVAILABLE", message: "Servico indisponivel." } },
      { status: 503 }
    );
  }

  const data = (await djangoResp.json().catch(() => ({
    error: { code: "BACKEND_ERROR", message: "Erro no servidor." },
  }))) as SetPasswordPayload;

  if (!djangoResp.ok) {
    return NextResponse.json(data, { status: djangoResp.status });
  }

  if (!data.access || !data.refresh) {
    return NextResponse.json(
      { error: { code: "MALFORMED_AUTH_RESPONSE", message: "Resposta de autenticacao incompleta." } },
      { status: 502 }
    );
  }

  let meResp: Response;
  try {
    meResp = await fetch(`${DJANGO_API}/api/v1/me`, {
      method: "GET",
      headers: {
        "X-Forwarded-Host": forwardedHost,
        Authorization: `Bearer ${data.access}`,
      },
    });
  } catch {
    return NextResponse.json(
      { error: { code: "BACKEND_UNAVAILABLE", message: "Servico indisponivel." } },
      { status: 503 }
    );
  }

  if (!meResp.ok) {
    return NextResponse.json(
      { error: { code: "SESSION_BOOTSTRAP_FAILED", message: "Nao foi possivel iniciar a sessao." } },
      { status: 502 }
    );
  }

  const user = (await meResp.json()) as UserDTO;
  const response = NextResponse.json({ user });
  setSessionCookies(response, data.access, data.refresh, user);

  return response;
}
