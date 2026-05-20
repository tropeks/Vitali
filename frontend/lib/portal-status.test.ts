import { describe, expect, it } from "vitest";

import { resolveBadgeMeta } from "./operational-ui";
import {
  PORTAL_ALLERGY_SEVERITY,
  PORTAL_APPOINTMENT_STATUS,
  PORTAL_ENCOUNTER_STATUS,
  PORTAL_PRESCRIPTION_STATUS,
  formatDateBR,
  formatDateTimeBR,
} from "./portal-status";

describe("portal-status maps", () => {
  it("appointment status maps use patient-friendly labels", () => {
    expect(PORTAL_APPOINTMENT_STATUS.waiting.label).toBe("Aguardando você");
    expect(PORTAL_APPOINTMENT_STATUS.in_progress.label).toBe("Em andamento");
    expect(PORTAL_APPOINTMENT_STATUS.no_show.label).toBe("Não compareceu");
  });

  it("prescription `signed` is labelled actionable to the patient", () => {
    // Staff dashboard says "Assinada"; portal explains what to do next.
    expect(PORTAL_PRESCRIPTION_STATUS.signed.label).toBe("Pronta para retirar");
    expect(PORTAL_PRESCRIPTION_STATUS.dispensed.label).toBe("Retirada concluída");
  });

  it("encounter `signed` is explicit to the patient", () => {
    expect(PORTAL_ENCOUNTER_STATUS.signed.label).toBe("Assinada pelo médico");
  });

  it("allergy severity preserves the staff-side palette", () => {
    expect(PORTAL_ALLERGY_SEVERITY.life_threatening.tone).toBe("critical");
    expect(PORTAL_ALLERGY_SEVERITY.life_threatening.badgeClass).toContain("red");
    expect(PORTAL_ALLERGY_SEVERITY.mild.tone).toBe("success");
  });

  it("resolveBadgeMeta works against the portal maps", () => {
    expect(resolveBadgeMeta(PORTAL_APPOINTMENT_STATUS, "confirmed")).toMatchObject({
      label: "Confirmada",
      tone: "info",
    });
    // Unknown status falls back to its raw value
    expect(resolveBadgeMeta(PORTAL_APPOINTMENT_STATUS, "weird")).toMatchObject({
      label: "weird",
      tone: "neutral",
    });
  });
});

describe("portal-status formatters", () => {
  it("formatDateBR formats ISO date as dd/mm/yyyy", () => {
    expect(formatDateBR("2026-05-20")).toMatch(/20\/05\/2026/);
  });

  it("formatDateTimeBR includes time", () => {
    const out = formatDateTimeBR("2026-05-20T15:30:00");
    expect(out).toMatch(/20\/05\/2026/);
    expect(out).toMatch(/15:30/);
  });

  it("empty / null values render as em-dash", () => {
    expect(formatDateBR(null)).toBe("—");
    expect(formatDateBR(undefined)).toBe("—");
    expect(formatDateTimeBR("")).toBe("—");
  });

  it("malformed input falls back to the raw value", () => {
    expect(formatDateBR("not-a-date")).toBeTruthy();
  });
});
