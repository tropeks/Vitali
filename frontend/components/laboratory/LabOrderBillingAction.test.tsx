import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LabOrderBillingAction from "./LabOrderBillingAction";
import { ApiError, apiFetch } from "@/lib/api";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LabOrderBillingAction", () => {
  it("does not render for orders that are not completed", () => {
    render(
      <LabOrderBillingAction order={{ id: "order-1", status: "ordered" }} />,
    );
    expect(
      screen.queryByRole("button", { name: /Faturar/ }),
    ).not.toBeInTheDocument();
  });

  it("faturas a completed order and redirects to the created guide", async () => {
    mockApiFetch.mockResolvedValue({ id: "guide-9" });
    render(
      <LabOrderBillingAction order={{ id: "order-1", status: "completed" }} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Faturar/ }));

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        "/api/v1/billing/guides/from-lab-order/",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ lab_order: "order-1" }),
        }),
      ),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/billing/guides/guide-9"),
    );
  });

  it("shows the pt-BR precondition message inline on a 400 without redirecting", async () => {
    mockApiFetch.mockRejectedValue(
      new ApiError(400, ["Pedido sem atendimento (encounter) não pode gerar guia."]),
    );
    render(
      <LabOrderBillingAction order={{ id: "order-1", status: "completed" }} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Faturar/ }));

    expect(
      await screen.findByText(
        "Pedido sem atendimento (encounter) não pode gerar guia.",
      ),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
