import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { GET } from './route';

vi.mock('@/lib/server/django-api', () => ({ djangoApiBaseUrl: () => 'http://django:8000' }));

describe('GET /api/subscription', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('normalizes a missing subscription to an empty successful response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"missing"}', { status: 404 }));
    const request = new NextRequest('https://clinic.example/api/subscription', {
      headers: { cookie: 'access_token=jwt', host: 'clinic.example' },
    });

    const response = await GET(request);
    expect(response.status).toBe(204);
    expect(await response.text()).toBe('');
  });

  it('forwards tenant host and the server-only access token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ plan_name: 'Demo' }),
    );
    const request = new NextRequest('https://clinic.example/api/subscription', {
      headers: { cookie: 'access_token=jwt', host: 'clinic.example' },
    });

    expect((await GET(request)).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://django:8000/api/v1/subscription/',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer jwt',
          'X-Forwarded-Host': 'clinic.example',
        }),
      }),
    );
  });
});
