import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LabTestFormModal from "./LabTestFormModal";
import { apiFetch } from "@/lib/api";
import type { LabTest } from "./types";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

// Mock the shared LOINC combobox: clicking it selects a governed LOINC row.
vi.mock("@/components/shared/RemoteCombobox", () => ({
  default: ({ onChange, value }: any) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          system: "loinc",
          code: "718-7",
          display: "Hemoglobina [Massa/volume] no sangue",
          active: true,
        })
      }
    >
      {value ? `LOINC ${value.code}` : "Buscar LOINC mock"}
    </button>
  ),
}));

const mockApiFetch = vi.mocked(apiFetch);

const existingTest: LabTest = {
  id: "test-1",
  code: "HB",
  name: "Hemoglobina",
  specimen_type: "Sangue",
  unit: "g/dL",
  reference_range: "12-16",
  active: true,
  category: "hematology",
  result_type: "numeric",
  method: "Fotometria",
  loinc_code: "",
  delta_threshold_pct: "10.00",
};

beforeEach(() => {
  vi.clearAllMocks();
  mockApiFetch.mockResolvedValue({ ...existingTest, loinc_code: "718-7" });
});

describe("LabTestFormModal", () => {
  it("round-trips delta_threshold_pct into the input and hints that empty = off", () => {
    render(
      <LabTestFormModal test={existingTest} onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    expect(
      screen.getByLabelText(/Limiar de delta-check/),
    ).toHaveValue(10);
    expect(
      screen.getByText(/Vazio.*delta-check.*desligad/i),
    ).toBeInTheDocument();
  });

  it("PATCHes loinc_code from the LOINC picker and the delta threshold", async () => {
    const onSaved = vi.fn();
    render(
      <LabTestFormModal test={existingTest} onClose={vi.fn()} onSaved={onSaved} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Buscar LOINC mock" }));
    expect(screen.getByRole("button", { name: "LOINC 718-7" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Limiar de delta-check/), {
      target: { value: "25" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        "/api/v1/lab-tests/test-1/",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    const body = JSON.parse(
      (mockApiFetch.mock.calls[0][1] as { body: string }).body,
    );
    expect(body.loinc_code).toBe("718-7");
    expect(body.delta_threshold_pct).toBe("25");
    expect(onSaved).toHaveBeenCalled();
  });

  it("sends delta_threshold_pct as null when the field is cleared", async () => {
    render(
      <LabTestFormModal test={existingTest} onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText(/Limiar de delta-check/), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled());
    const body = JSON.parse(
      (mockApiFetch.mock.calls[0][1] as { body: string }).body,
    );
    expect(body.delta_threshold_pct).toBeNull();
  });

  it("POSTs a new test when created without an id", async () => {
    render(<LabTestFormModal test={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Código *"), {
      target: { value: "GLI" },
    });
    fireEvent.change(screen.getByLabelText("Nome *"), {
      target: { value: "Glicose" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        "/api/v1/lab-tests/",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
