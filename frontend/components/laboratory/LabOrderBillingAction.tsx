"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileText } from "lucide-react";
import { ApiError, apiFetch } from "@/lib/api";

// A6 — bill a COMPLETED LabOrder into a TISS SP/SADT guide.
// POST /api/v1/billing/guides/from-lab-order/ { lab_order } → 201/200 with the
// guide (has `id`) → redirect to /billing/guides/<id>. A 400 carries a clear
// pt-BR precondition message which we surface inline instead of crashing.

interface BillableOrder {
  id: string;
  status: string;
}

interface Props {
  order: BillableOrder;
  /** Optional hook to refresh the caller's list after a successful billing. */
  onBilled?: () => void;
}

/** Pull the server's pt-BR message out of the various DRF error shapes. */
function extractMessage(err: unknown): string {
  const fallback = "Não foi possível faturar este pedido.";
  const body = err instanceof ApiError ? err.body : undefined;
  if (typeof body === "string" && body.trim()) return body;
  if (Array.isArray(body) && typeof body[0] === "string") return body[0];
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const nonField = record.non_field_errors;
    if (Array.isArray(nonField) && typeof nonField[0] === "string") {
      return nonField[0];
    }
  }
  return fallback;
}

export default function LabOrderBillingAction({ order, onBilled }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (order.status !== "completed") return null;

  async function bill() {
    setBusy(true);
    setError("");
    try {
      const guide = await apiFetch<{ id: string }>(
        "/api/v1/billing/guides/from-lab-order/",
        {
          method: "POST",
          body: JSON.stringify({ lab_order: order.id }),
        },
      );
      onBilled?.();
      router.push(`/billing/guides/${guide.id}`);
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={busy}
        onClick={bill}
        className="neu-btn inline-flex items-center gap-1.5 px-3 py-2 text-xs disabled:opacity-50"
      >
        <FileText aria-hidden="true" size={14} />
        {busy ? "Faturando…" : "Faturar (SP/SADT)"}
      </button>
      {error && (
        <p role="alert" className="max-w-xs text-right text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
