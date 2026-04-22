/**
 * Next.js API Route: POST /api/auth/login
 *
 * Proxies credentials to Django, then sets httpOnly cookies for
 * access_token and refresh_token, and a readable cookie for UserDTO.
 */
import { NextRequest, NextResponse } from "next/server";

const DJANGO_API =
  process.env.DJANGO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";
const IS_PROD = process.env.NODE_ENV === "production";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.email || !body?.password) {
    return NextResponse.json(
      { error: { code: "VALIDATION_ERROR", message: "email e password obrigatórios." } },
      { status: 400 }
    );
  }

  // Forward the original Host header so django-tenants can identify the tenant schema.
  // Strip port — Domain rows store "localhost", not "localhost:3000".
  // Without this, server-to-server calls from inside Docker use "django:8000" as the Host,
  // which doesn't match any Domain row and falls through to the public schema.
  const rawHost = req.headers.get("host") ?? "localhost";
  const forwardedHost = rawHost.split(":")[0];

  let djangoResp: Response;
  try {
    djangoResp = await fetch(`${DJANGO_API}/api/v1/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Node.js fetch() cannot set Host directly (Fetch API spec forbids it).
        // Use X-Forwarded-Host instead; Django reads this when USE_X_FORWARDED_HOST=True.
        "X-Forwarded-Host": forwardedHost,
      },
      body: JSON.stringify({ email: body.email, password: body.password }),
    });
  } catch {
    return NextResponse.json(
      { error: { code: "BACKEND_UNAVAILABLE", message: "Serviço indisponível." } },
      { status: 503 }
    );
  }

  if (!djangoResp.ok) {
    // Avoid crashing if Django returns a non-JSON error page (e.g. 404 HTML)
    const data = await djangoResp.json().catch(() => ({
      error: { code: "BACKEND_ERROR", message: "Erro no servidor." },
    }));
    return NextResponse.json(data, { status: djangoResp.status });
  }

  const data = await djangoResp.json();

  const { access, refresh, user, mfa_required } = data as {
    access: string;
    refresh: string;
    user: Record<string, unknown>;
    mfa_required?: boolean;
  };

  // Access token expires in 15 min; refresh in 7 days
  const accessMaxAge = 15 * 60;
  const refreshMaxAge = 7 * 24 * 60 * 60;

  const response = NextResponse.json({ user, mfa_required: !!mfa_required });

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
