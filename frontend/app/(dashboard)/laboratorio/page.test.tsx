import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LaboratorioPage from "./page";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const mockApiFetch = vi.mocked(apiFetch);

const testCatalog = {
  count: 1,
  results: [{
    id: "test-1",
    code: "HMG",
    name: "Hemograma",
    specimen_type: "Sangue",
    unit: "",
    reference_range: "",
    active: true,
  }],
};

const testOrders = {
  count: 1,
  results: [{
    id: "order-1",
    patient: "patient-1",
    patient_name: "Maria Souza",
    patient_mrn: "000123",
    encounter: null,
    status: "ordered",
    status_display: "Solicitado",
    clinical_indication: "Investigação de anemia",
    requested_by_name: "Dra. Ana",
    requested_at: "2026-07-21T12:00:00Z",
    items: [{
      id: "item-1",
      test_name: "Hemograma",
      unit: "g/dL",
      reference_range: "12–16",
      result_value: "",
      abnormal_flag: "undetermined",
      abnormal_flag_display: "Indeterminado",
      result_notes: "",
      is_validated: false,
    }],
  }],
};

function installSuccessfulApi() {
  mockApiFetch.mockImplementation(async (path, options) => {
    if (path.startsWith("/api/v1/lab-tests/")) return testCatalog;
    if (path === "/api/v1/lab-orders/" && options?.method === "POST") return { id: "order-2" };
    if (path === "/api/v1/lab-orders/") return testOrders;
    if (path.startsWith("/api/v1/patients/")) {
      return { results: [{ id: "patient-1", full_name: "Maria Souza", medical_record_number: "000123" }] };
    }
    return {};
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  installSuccessfulApi();
});

describe("LaboratorioPage", () => {
  it("normaliza respostas paginadas e exibe os pedidos", async () => {
    render(<LaboratorioPage />);

    expect(await screen.findByRole("heading", { name: "Maria Souza" })).toBeInTheDocument();
    expect(screen.getByText("Hemograma")).toBeInTheDocument();
    expect(screen.getByText("Solicitado")).toBeInTheDocument();
    expect(screen.getByText("Pendentes").nextElementSibling).toHaveTextContent("1");
  });

  it("cria pedido com paciente e exames selecionados", async () => {
    render(<LaboratorioPage />);
    await screen.findByRole("heading", { name: "Maria Souza" });

    fireEvent.click(screen.getByRole("button", { name: "Novo pedido" }));
    const patientSearch = screen.getByRole("combobox", { name: "Paciente" });
    fireEvent.change(patientSearch, { target: { value: "Maria" } });
    fireEvent.click(await screen.findByRole("option", { name: /Maria Souza/ }, { timeout: 1000 }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Hemograma/ }));
    fireEvent.change(screen.getByLabelText("Indicação clínica"), {
      target: { value: "Controle clínico" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar pedido" }));

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith("/api/v1/lab-orders/", {
        method: "POST",
        body: JSON.stringify({
          patient: "patient-1",
          test_ids: ["test-1"],
          clinical_indication: "Controle clínico",
        }),
      });
    });
    expect(screen.queryByRole("heading", { name: "Novo pedido laboratorial" })).not.toBeInTheDocument();
  });

  it("informa a falha de uma coleta sem esconder o pedido", async () => {
    installSuccessfulApi();
    mockApiFetch.mockImplementation(async (path, options) => {
      if (path.startsWith("/api/v1/lab-tests/")) return testCatalog;
      if (path === "/api/v1/lab-orders/") return testOrders;
      if (path.includes("/collect/") && options?.method === "POST") throw new Error("conflict");
      return {};
    });

    render(<LaboratorioPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Registrar coleta" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível registrar a coleta.");
    expect(screen.getByRole("heading", { name: "Maria Souza" })).toBeInTheDocument();
  });
});
