import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { portalApi } from "@/lib/portal-api";
import PortalImagingPage from "./page";

vi.mock("@/lib/portal-api", async (original) => {
  const actual = await original<typeof import("@/lib/portal-api")>();
  return { ...actual, portalApi: { ...actual.portalApi, getMyImagingStudies: vi.fn() } };
});

describe("PortalImagingPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra somente a identidade Vitali ao abrir imagens e laudo", async () => {
    vi.mocked(portalApi.getMyImagingStudies).mockResolvedValue([{
      id: "study-1",
      accession_number: "IMG-42",
      study_instance_uid: "1.2.3.4",
      modality: "CT",
      body_part_examined: "Tórax",
      description: "Tomografia de tórax",
      study_date: "2026-07-21",
      series_count: 2,
      instance_count: 80,
      available: true,
      report_url: "/api/v1/portal/me/imaging-studies/study-1/report/",
      viewer_url: "/viewer/study-1",
    }]);

    render(<PortalImagingPage />);

    expect(await screen.findByRole("heading", { name: "Tomografia de tórax" })).toBeInTheDocument();
    expect(screen.getByTitle("Visualizador Vitali — Tomografia de tórax")).toHaveAttribute("src", "/viewer/study-1");
    expect(screen.getByRole("link", { name: /Ver laudo assinado/ })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Orthanc|OHIF|PACS/i);
  });

  it("explica quando ainda não há exames liberados", async () => {
    vi.mocked(portalApi.getMyImagingStudies).mockResolvedValue([]);
    render(<PortalImagingPage />);
    expect(await screen.findByText("Nenhum exame de imagem liberado")).toBeInTheDocument();
  });
});
