import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/server/django-api", () => ({ djangoApiBaseUrl: () => "http://django:8000" }));

const cookieStore = new Map<string, { value: string }>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => cookieStore.get(name),
  }),
}));

// Imported after the mocks above so route.ts picks them up.
const { POST } = await import("./route");

function logoutRequest() {
  return new NextRequest("https://clinic.example/api/auth/logout", {
    method: "POST",
    headers: { host: "clinic.example" },
  });
}

describe("POST /api/auth/logout", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    cookieStore.clear();
  });

  it("clears every auth cookie, including the legacy access_token_js mirror for pre-existing sessions", async () => {
    cookieStore.set("access_token", { value: "access-jwt" });
    cookieStore.set("refresh_token", { value: "refresh-jwt" });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 200 }));

    const response = await POST(logoutRequest());

    expect(response.status).toBe(200);
    for (const name of ["access_token", "access_token_js", "refresh_token", "vitali_user"]) {
      const cleared = response.cookies.get(name);
      expect(cleared, `expected ${name} to be cleared`).toMatchObject({ value: "", maxAge: 0 });
    }
  });

  it("still clears cookies even when Django is unreachable", async () => {
    cookieStore.set("access_token", { value: "access-jwt" });
    cookieStore.set("refresh_token", { value: "refresh-jwt" });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await POST(logoutRequest());

    expect(response.status).toBe(200);
    expect(response.cookies.get("access_token")).toMatchObject({ value: "", maxAge: 0 });
  });
});
