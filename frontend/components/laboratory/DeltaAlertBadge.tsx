import { TrendingUp } from "lucide-react";
import type { LabDeltaAlert } from "./types";

// A4-b — delta-check callout surfaced on a resulted LabOrderItem whenever the
// server attached a `delta_alert` (the variation exceeded the test's
// delta_threshold_pct). Absent alert renders nothing.

interface Props {
  alert: LabDeltaAlert | null | undefined;
}

export default function DeltaAlertBadge({ alert }: Props) {
  if (!alert) return null;
  return (
    <div
      role="alert"
      className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
    >
      <span className="inline-flex items-center gap-1 font-semibold">
        <TrendingUp aria-hidden="true" size={14} />
        {"⚠"} Variação {alert.delta_pct}% (limite {alert.threshold_pct}%)
      </span>
      <span className="font-mono">
        {alert.previous_value} {"→"} {alert.current_value}
      </span>
    </div>
  );
}
