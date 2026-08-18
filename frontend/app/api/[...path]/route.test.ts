import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

vi.mock("@/lib/server/django-api", () => ({ djangoApiBaseUrl: () => "http://django:8000" }));

function apiRequest(path: string, cookie?: string, extraHeaders?: Record<string, string>) {
  const headers: Record<string, string> = { host: "clinic.example", ...extraHeaders };
  if (cookie) headers.cookie = cookie;
  return new NextRequest(`https://clinic.example${path}`, { headers });
}

describe("GET/POST /api/* proxy", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("injects Authorization from the httpOnly access_token cookie — the client never holds the token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ ok: true }));

    const response = await GET(apiRequest("/api/v1/patients/", "access_token=server-side-jwt"));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://django:8000/api/v1/patients/",
      expect.objectContaining({
        headers: expect.objectContaining({ get: expect.any(Function) }),
      })
    );
    const [, init] = fetchMock.mock.calls[0];
    const forwarded = init?.headers as Headers;
    expect(forwarded.get("Authorization")).toBe("Bearer server-side-jwt");
  });

  it("discards any Authorization header the client sent — only the httpOnly cookie is trusted", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ ok: true }));

    await GET(
      apiRequest("/api/v1/patients/", "access_token=real-jwt", {
        authorization: "Bearer forged-by-client",
      })
    );

    const [, init] = fetchMock.mock.calls[0];
    const forwarded = init?.headers as Headers;
    expect(forwarded.get("Authorization")).toBe("Bearer real-jwt");
  });

  it("sends no Authorization header when there is no access_token cookie (logged out)", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ detail: "Unauthorized" }, { status: 401 }));

    await GET(apiRequest("/api/v1/patients/"));

    const [, init] = fetchMock.mock.calls[0];
    const forwarded = init?.headers as Headers;
    expect(forwarded.has("Authorization")).toBe(false);
  });
});
