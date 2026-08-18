import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const ORIGINAL_CSP_ENFORCE = process.env.CSP_ENFORCE;

afterEach(() => {
  if (ORIGINAL_CSP_ENFORCE === undefined) delete process.env.CSP_ENFORCE;
  else process.env.CSP_ENFORCE = ORIGINAL_CSP_ENFORCE;
  vi.resetModules();
});

function dashboardRequest() {
  return new NextRequest("https://clinic.example/dashboard", {
    headers: { host: "clinic.example" },
  });
}

describe("middleware CSP enforcement default (item 3.8)", () => {
  // lib/security/csp.ts documents this project's rollout: Report-Only first,
  // confirm a clean soak against the violation collector, THEN promote. No soak
  // has run yet, so the default stays Report-Only — enforcing a policy nobody
  // has observed can block a legitimate resource and take the app down.
  it("stays Report-Only by default when CSP_ENFORCE is unset", async () => {
    delete process.env.CSP_ENFORCE;
    vi.resetModules();
    const { middleware } = await import("./middleware");

    const response = middleware(dashboardRequest());

    expect(response.headers.get("Content-Security-Policy-Report-Only")).toBeTruthy();
    expect(response.headers.get("Content-Security-Policy")).toBeNull();
  });

  it("promotes to enforcing when CSP_ENFORCE=true", async () => {
    process.env.CSP_ENFORCE = "true";
    vi.resetModules();
    const { middleware } = await import("./middleware");

    const response = middleware(dashboardRequest());

    expect(response.headers.get("Content-Security-Policy")).toBeTruthy();
    expect(response.headers.get("Content-Security-Policy-Report-Only")).toBeNull();
  });
});
