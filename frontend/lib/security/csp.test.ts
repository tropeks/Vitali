import { describe, expect, it } from "vitest";

import {
  buildContentSecurityPolicy,
  cspHeaderName,
  CSP_REPORT_PATH,
  generateNonce,
  STATIC_SECURITY_HEADERS,
} from "./csp";

function directives(csp: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const part of csp.split(";").map((p) => p.trim()).filter(Boolean)) {
    const [name, ...rest] = part.split(/\s+/);
    map.set(name, rest.join(" "));
  }
  return map;
}

describe("generateNonce", () => {
  it("produces a unique, decodable base64 string per call", () => {
    const a = generateNonce();
    const b = generateNonce();
    expect(a).not.toBe(b);
    // 16 random bytes → 24-char base64 (with padding); must round-trip.
    expect(atob(a)).toHaveLength(16);
    expect(a).toMatch(/^[A-Za-z0-9+/]+={0,2}$/);
  });
});

describe("buildContentSecurityPolicy", () => {
  const nonce = "TESTNONCE123456==";

  it("binds script-src to the request nonce with strict-dynamic", () => {
    const d = directives(buildContentSecurityPolicy({ nonce }));
    expect(d.get("script-src")).toContain(`'nonce-${nonce}'`);
    expect(d.get("script-src")).toContain("'strict-dynamic'");
  });

  it("omits 'unsafe-eval' in production but allows it in dev", () => {
    expect(buildContentSecurityPolicy({ nonce })).not.toContain("'unsafe-eval'");
    expect(buildContentSecurityPolicy({ nonce, isDev: true })).toContain("'unsafe-eval'");
  });

  it("locks down framing and object embedding", () => {
    const d = directives(buildContentSecurityPolicy({ nonce }));
    expect(d.get("frame-ancestors")).toBe("'none'");
    expect(d.get("object-src")).toBe("'none'");
    expect(d.get("base-uri")).toBe("'self'");
  });

  it("points report-uri at the same-origin collector path", () => {
    expect(buildContentSecurityPolicy({ nonce })).toContain(`report-uri ${CSP_REPORT_PATH}`);
  });

  it("upgrades insecure requests only when enforcing outside dev", () => {
    expect(buildContentSecurityPolicy({ nonce })).not.toContain("upgrade-insecure-requests");
    expect(buildContentSecurityPolicy({ nonce, enforce: true })).toContain(
      "upgrade-insecure-requests",
    );
    expect(buildContentSecurityPolicy({ nonce, enforce: true, isDev: true })).not.toContain(
      "upgrade-insecure-requests",
    );
  });

  it("allows Sentry ingest + replay worker without hardcoding the DSN host", () => {
    const d = directives(buildContentSecurityPolicy({ nonce }));
    expect(d.get("connect-src")).toContain("https:");
    expect(d.get("worker-src")).toContain("blob:");
  });
});

describe("cspHeaderName", () => {
  it("is Report-Only until enforcement is promoted", () => {
    expect(cspHeaderName(false)).toBe("Content-Security-Policy-Report-Only");
    expect(cspHeaderName(true)).toBe("Content-Security-Policy");
  });
});

describe("STATIC_SECURITY_HEADERS", () => {
  it("denies framing and sniffing", () => {
    expect(STATIC_SECURITY_HEADERS["X-Frame-Options"]).toBe("DENY");
    expect(STATIC_SECURITY_HEADERS["X-Content-Type-Options"]).toBe("nosniff");
  });
});
