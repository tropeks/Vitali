/**
 * Catch-all proxy API route: /api/* → Django backend
 *
 * Why this exists instead of next.config.mjs rewrites:
 * Next.js normalizes trailing slashes before applying rewrites (strips them),
 * but Django DRF URL patterns require trailing slashes. This proxy preserves
 * them explicitly. It also sets X-Forwarded-Host for django-tenants routing,
 * since Node.js fetch() cannot set the Host header (Fetch spec forbids it).
 *
 * Specific routes under /api/auth/* (login, refresh, logout) are handled by
 * their own dedicated route files and take precedence over this catch-all.
 */
import { NextRequest, NextResponse } from "next/server";

const DJANGO_API =
  process.env.DJANGO_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://django:8000";

async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;

  // Always forward with trailing slash — Django DRF URL patterns require it.
  const djangoPath = pathname.endsWith("/") ? pathname : pathname + "/";
  const djangoUrl = `${DJANGO_API}${djangoPath}${search}`;

  const rawHost = request.headers.get("host") ?? "localhost";
  const forwardedHost = rawHost.split(":")[0];

  // Build forwarded headers
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    // Skip headers that should not be forwarded to the backend
    if (key.toLowerCase() === "host") return;
    headers.set(key, value);
  });
  headers.set("X-Forwarded-Host", forwardedHost);

  let body: BodyInit | undefined;
  if (!["GET", "HEAD"].includes(request.method)) {
    body = await request.arrayBuffer();
  }

  let djangoResp: Response;
  try {
    djangoResp = await fetch(djangoUrl, {
      method: request.method,
      headers,
      body,
    });
  } catch {
    return NextResponse.json({ error: "Backend unavailable." }, { status: 503 });
  }

  const responseHeaders = new Headers();
  djangoResp.headers.forEach((value, key) => {
    // Do not forward hop-by-hop headers
    if (["connection", "transfer-encoding", "keep-alive"].includes(key.toLowerCase())) return;
    responseHeaders.set(key, value);
  });

  return new NextResponse(djangoResp.body, {
    status: djangoResp.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
