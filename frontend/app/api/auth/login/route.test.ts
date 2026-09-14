import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

vi.mock("@/lib/server/django-api", () => ({ djangoApiBaseUrl: () => "http://django:8000" }));

function loginRequest(email = "a@b.com", password = "secret123") {
  return new NextRequest("https://clinic.example/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json", host: "clinic.example" },
    body: JSON.stringify({ email, password }),
  });
}

describe("POST /api/auth/login", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("sets only the httpOnly access_token cookie — no client-readable access_token_js mirror", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        access: "access-jwt",
        refresh: "refresh-jwt",
        user: { id: "1", email: "a@b.com" },
      })
    );

    const response = await POST(loginRequest());

    expect(response.status).toBe(200);

    const access = response.cookies.get("access_token");
    expect(access).toMatchObject({ value: "access-jwt", httpOnly: true, path: "/" });

    // The non-httpOnly mirror must no longer exist.
    expect(response.cookies.get("access_token_js")).toBeUndefined();

    const refresh = response.cookies.get("refresh_token");
    expect(refresh).toMatchObject({ value: "refresh-jwt", httpOnly: true });

    // vitali_user stays readable — it's the client's source for hasPermission(),
    // not the JWT.
    const userCookie = response.cookies.get("vitali_user");
    expect(userCookie).toMatchObject({ value: JSON.stringify({ id: "1", email: "a@b.com" }), httpOnly: false });
  });
});
