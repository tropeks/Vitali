import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import CommandPalette from "./CommandPalette";
import type { UserDTO } from "@/lib/auth";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { apiFetch } from "@/lib/api";
vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
const apiFetchMock = vi.mocked(apiFetch);

const MODULES = ["emr", "billing", "pharmacy", "rh", "imaging"];

const fullUser: UserDTO = {
  id: "u-1",
  full_name: "E2E Admin",
  email: "admin@test.com",
  role_name: "admin",
  permissions: [
    "admin",
    "emr.read",
    "patients.read",
    "schedule.read",
    "billing.read",
    "billing.full",
    "imaging.read",
    "organization.read",
    "mpi.read",
    "workflow.read",
    "hr.manage",
    "pharmacy.read",
    "pharmacy.stock_manage",
  ],
  active_modules: MODULES,
  is_superuser: false,
};

// A minimal-permission clinician: EMR read only.
const emrOnlyUser: UserDTO = {
  ...fullUser,
  id: "u-2",
  permissions: ["emr.read"],
};

function openPalette() {
  fireEvent.keyDown(window, { key: "k", metaKey: true });
}

beforeEach(() => {
  vi.clearAllMocks();
  apiFetchMock.mockResolvedValue({ results: [] });
});

describe("CommandPalette", () => {
  it("opens on ⌘K and closes on Esc", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    openPalette();
    expect(screen.getByRole("dialog", { name: "Ir para" })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("also opens on Ctrl+K", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("filters nav items by substring (accent-insensitive)", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();

    // Unfiltered: Pacientes is present.
    expect(screen.getByRole("option", { name: /Pacientes/ })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "faturam" } });
    expect(screen.getByRole("option", { name: "Faturamento" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^Pacientes$/ })).not.toBeInTheDocument();
  });

  it("hides nav items the user cannot see and shows them when permitted", () => {
    const { rerender } = render(
      <CommandPalette user={emrOnlyUser} activeModules={MODULES} />,
    );
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "faturam" } });
    // emr.read only → no billing.* → Faturamento must NOT be reachable.
    expect(screen.queryByRole("option", { name: "Faturamento" })).not.toBeInTheDocument();

    rerender(<CommandPalette user={fullUser} activeModules={MODULES} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "faturam" } });
    expect(screen.getByRole("option", { name: "Faturamento" })).toBeInTheDocument();
  });

  it("respects the module gate (hides Concessão when the module is inactive)", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "concess" } });
    expect(screen.queryByRole("option", { name: /Concessão/ })).not.toBeInTheDocument();
  });

  it("debounce-searches patients against /api/v1/patients/?search=<q>", async () => {
    apiFetchMock.mockResolvedValue({
      results: [
        { id: 42, full_name: "Maria Silva", medical_record_number: "MRN-42", age: 30 },
      ],
    });
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "maria" } });

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/patients/?search=maria"),
      ),
    );
    expect(await screen.findByRole("option", { name: /Maria Silva/ })).toBeInTheDocument();
  });

  it("does not hit the patients API for queries under 2 chars", async () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "m" } });
    // Give the debounce a chance to (not) fire.
    await new Promise((r) => setTimeout(r, 350));
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("navigates on Enter to the highlighted nav destination", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Pacientes" } });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/patients");
  });

  it("navigates to a patient on click", async () => {
    apiFetchMock.mockResolvedValue({
      results: [{ id: 7, full_name: "João Souza", medical_record_number: "MRN-7" }],
    });
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "joao" } });

    const row = await screen.findByRole("option", { name: /João Souza/ });
    fireEvent.click(row);
    expect(push).toHaveBeenCalledWith("/patients/7");
  });

  it("moves the active row with ArrowDown and navigates it on Enter", () => {
    render(<CommandPalette user={fullUser} activeModules={MODULES} />);
    openPalette();
    // First nav row is Dashboard (HOME_ITEM). ArrowDown → second row.
    const combobox = screen.getByRole("combobox");
    fireEvent.keyDown(combobox, { key: "ArrowDown" });
    fireEvent.keyDown(combobox, { key: "Enter" });
    // Second destination is the first NAV_GROUPS item the admin can see (Pacientes).
    expect(push).toHaveBeenCalledWith("/patients");
  });
});
