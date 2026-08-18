import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

vi.mock("@/lib/server/django-api", () => ({ djangoApiBaseUrl: () => "http://django:8000" }));

/**
 * Builds a JWT-shaped (but unsigned/garbage-signature) token: three
 * base64url segments, exactly the shape the real attack in item 0.6
 * exploits — a client can craft this string itself and POST it here.
 * Only Django's signature check (mocked via fetch below) can tell a real
 * token from this kind of forgery.
 */
function fakeJwt(payload: Record<string, unknown>): string {
  const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${header}.${body}.forged-signature`;
}

function postRequest(access: string, refresh = "refresh-token") {
  return new NextRequest("https://clinic.example/api/auth/mfa-complete", {
    method: "POST",
    headers: { "content-type": "application/json", host: "clinic.example" },
    body: JSON.stringify({ access, refresh }),
  });
}

describe("POST /api/auth/mfa-complete", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("rejects a forged token that Django's signature check refuses, and sets no cookie (fails on old code)", async () => {
    // The token looks legitimate (claims mfa_verified=true) but Django is the
    // only party who can verify the signature — mock it refusing the token.
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ detail: "invalid signature" }, { status: 401 }));

    const forged = fakeJwt({ mfa_verified: true, sub: "1" });
    const response = await POST(postRequest(forged));

    expect(response.status).toBe(401);
    expect(response.cookies.get("access_token")).toBeUndefined();
    expect(response.cookies.get("access_token_js")).toBeUndefined();
    expect(response.cookies.get("refresh_token")).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://django:8000/api/v1/me",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: `Bearer ${forged}` }),
      })
    );
  });

  it("accepts a token Django validates and writes cookies with the original attributes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ id: "1", email: "a@b.com" }, { status: 200 }));

    const valid = fakeJwt({ mfa_verified: true, sub: "1" });
    const response = await POST(postRequest(valid, "refresh-value"));

    expect(response.status).toBe(200);

    const access = response.cookies.get("access_token");
    expect(access).toMatchObject({
      value: valid,
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 15 * 60,
    });

    const accessJs = response.cookies.get("access_token_js");
    expect(accessJs).toMatchObject({
      value: valid,
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: 15 * 60,
    });

    const refresh = response.cookies.get("refresh_token");
    expect(refresh).toMatchObject({
      value: "refresh-value",
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 7 * 24 * 60 * 60,
    });
  });

  it("rejects when the backend round-trip fails (network error) and sets no cookie", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const valid = fakeJwt({ mfa_verified: true, sub: "1" });
    const response = await POST(postRequest(valid));

    expect(response.status).toBeGreaterThanOrEqual(401);
    expect(response.cookies.get("access_token")).toBeUndefined();
    expect(response.cookies.get("refresh_token")).toBeUndefined();
  });

  it("rejects a token missing the mfa_verified claim without even calling the backend", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    const noClaim = fakeJwt({ sub: "1" });
    const response = await POST(postRequest(noClaim));

    expect(response.status).toBe(401);
    expect(response.cookies.get("access_token")).toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("still returns 400 for a malformed request body (missing fields)", async () => {
    const response = await POST(postRequest("", ""));
    // access="" is falsy, so the pre-check for required fields fires.
    expect(response.status).toBe(400);
  });
});
