import { NextRequest, NextResponse } from 'next/server';
import { djangoApiBaseUrl } from '@/lib/server/django-api';

/**
 * Normalizes the expected "tenant has no subscription" response to 204 so the
 * settings screen does not generate a failed-request entry in the browser.
 */
export async function GET(request: NextRequest) {
  const access = request.cookies.get('access_token')?.value;
  if (!access) return new NextResponse(null, { status: 401 });

  const host = (request.headers.get('host') ?? 'localhost').split(':')[0];
  let response: Response;
  try {
    response = await fetch(`${djangoApiBaseUrl()}/api/v1/subscription/`, {
      headers: {
        Authorization: `Bearer ${access}`,
        'X-Forwarded-Host': host,
        'X-Forwarded-Proto': 'https',
      },
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ error: 'Backend unavailable.' }, { status: 503 });
  }

  if (response.status === 404) return new NextResponse(null, { status: 204 });
  return new NextResponse(response.body, {
    status: response.status,
    headers: { 'content-type': response.headers.get('content-type') ?? 'application/json' },
  });
}
