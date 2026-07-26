import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DeltaAlertBadge from "./DeltaAlertBadge";
import type { LabDeltaAlert } from "./types";

const alert: LabDeltaAlert = {
  id: "alert-1",
  order_item: "item-1",
  previous_item: "item-0",
  test: "test-1",
  previous_value: "12.0",
  current_value: "18.5",
  delta_absolute: "6.5",
  delta_pct: "54.17",
  threshold_pct: "20.00",
  created_at: "2026-07-24T10:00:00Z",
};

describe("DeltaAlertBadge", () => {
  it("renders the delta variation and threshold when an alert is present", () => {
    render(<DeltaAlertBadge alert={alert} />);
    const region = screen.getByRole("alert");
    expect(region).toHaveTextContent("Variação 54.17%");
    expect(region).toHaveTextContent("limite 20.00%");
    // previous → current values are shown
    expect(region).toHaveTextContent("12.0");
    expect(region).toHaveTextContent("18.5");
  });

  it("renders nothing when the alert is absent", () => {
    const { container } = render(<DeltaAlertBadge alert={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
