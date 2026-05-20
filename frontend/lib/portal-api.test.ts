/**
 * Tests for the typed portal-api fetch wrapper. Mocks global `fetch` and
 * asserts the error-class routing (401 → PortalUnauthorizedError, 403 →
 * PortalNotActiveError, anything else → PortalApiError).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PortalApiError,
  PortalNotActiveError,
  PortalUnauthorizedError,
  portalApi,
} from "./portal-api";

const originalFetch = global.fetch;

function mockFetch(status: number, body: unknown) {
  global.fetch = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

beforeEach(() => {
  // Ensure no stale cookie picks up between tests.
  Object.defineProperty(document, "cookie", { value: "", writable: true });
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("portalApi.getMyProfile", () => {
  it("returns the parsed body on 200", async () => {
    mockFetch(200, { id: "p-1", full_name: "Ana" });
    const profile = await portalApi.getMyProfile();
    expect(profile.id).toBe("p-1");
    expect(profile.full_name).toBe("Ana");
  });

  it("throws PortalUnauthorizedError on 401", async () => {
    mockFetch(401, { detail: "Unauthorized" });
    await expect(portalApi.getMyProfile()).rejects.toBeInstanceOf(
      PortalUnauthorizedError,
    );
  });

  it("throws PortalNotActiveError on 403", async () => {
    mockFetch(403, { detail: "Portal access not active" });
    await expect(portalApi.getMyProfile()).rejects.toBeInstanceOf(
      PortalNotActiveError,
    );
  });

  it("throws PortalApiError on 500", async () => {
    mockFetch(500, { detail: "boom" });
    await expect(portalApi.getMyProfile()).rejects.toBeInstanceOf(PortalApiError);
  });
});

describe("portalApi other endpoints", () => {
  it("getMyAppointments hits /portal/me/appointments/", async () => {
    const calls: Array<[unknown, unknown]> = [];
    global.fetch = (async (url: unknown, init: unknown) => {
      calls.push([url, init]);
      return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
    }) as unknown as typeof fetch;
    await portalApi.getMyAppointments();
    expect(String(calls[0][0])).toMatch(/\/api\/v1\/portal\/me\/appointments\/$/);
  });

  it("activateInvite POSTs the token to the activate endpoint", async () => {
    const calls: Array<[unknown, RequestInit | undefined]> = [];
    global.fetch = (async (url: unknown, init: RequestInit | undefined) => {
      calls.push([url, init]);
      return {
        ok: true,
        status: 200,
        json: async () => ({ id: "x", status: "active" }),
      } as Response;
    }) as unknown as typeof fetch;
    const out = await portalApi.activateInvite("abc-xyz");
    expect(out.status).toBe("active");
    expect(calls[0][1]?.method).toBe("POST");
    expect(calls[0][1]?.body).toBe(JSON.stringify({ invite_token: "abc-xyz" }));
  });
});
