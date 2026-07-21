import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { portalApi } from "@/lib/portal-api";
import PortalLabResultsPage from "./page";

vi.mock("@/lib/portal-api", async (original) => {
  const actual = await original<typeof import("@/lib/portal-api")>();
  return {
    ...actual,
    portalApi: {
      ...actual.portalApi,
      getMyLabResults: vi.fn(),
      downloadLabReport: vi.fn(),
    },
  };
});

describe("PortalLabResultsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra apenas os laudos devolvidos pela superfície self-service", async () => {
    vi.mocked(portalApi.getMyLabResults).mockResolvedValue([
      {
        id: "order-1",
        accession_number: "LAB-42",
        requested_at: "2026-07-21T10:00:00Z",
        completed_at: "2026-07-21T12:00:00Z",
        clinical_indication: "",
        report_url: "/report/",
        items: [
          {
            id: "item-1",
            test_name: "Glicose",
            category: "biochemistry",
            method: "Enzimático",
            specimen_type: "Soro",
            unit: "mg/dL",
            reference_range: "70–99",
            result_value: "90",
            abnormal_flag: "normal",
            abnormal_flag_display: "Normal",
            result_notes: "",
            validated_at: "2026-07-21T12:00:00Z",
          },
        ],
      },
    ]);
    render(<PortalLabResultsPage />);
    expect(
      await screen.findByRole("heading", { name: "Laudo LAB-42" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Glicose")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Baixar laudo PDF/ }),
    ).toBeInTheDocument();
  });
});
