"use client";

import { Download, FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";

import {
  portalApi,
  PortalApiError,
  type PortalLabOrder,
} from "@/lib/portal-api";

export default function PortalLabResultsPage() {
  const [orders, setOrders] = useState<PortalLabOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    portalApi
      .getMyLabResults()
      .then(setOrders)
      .catch((err) => {
        if (err instanceof PortalApiError && [401, 403].includes(err.status)) {
          window.location.assign(
            err.status === 401 ? "/portal/login" : "/portal/activate",
          );
        } else setError("Não foi possível carregar seus resultados.");
      })
      .finally(() => setLoading(false));
  }, []);

  async function download(order: PortalLabOrder) {
    setDownloading(order.id);
    try {
      const blob = await portalApi.downloadLabReport(order.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `laudo-${order.accession_number || order.id}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Não foi possível baixar o laudo.");
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-neu-ink">Resultados de exames</h1>
        <p className="mt-1 text-sm text-neu-inkSoft">
          Somente resultados concluídos, validados e liberados pela clínica.
        </p>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}
      {loading ? (
        <div
          role="status"
          className="neu-panel p-8 text-center text-sm text-neu-inkSoft"
        >
          Carregando resultados…
        </div>
      ) : (
        orders.map((order) => (
          <article key={order.id} className="neu-panel overflow-hidden">
            <header className="flex flex-col gap-3 border-b border-neu-app p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-semibold text-neu-ink">
                  Laudo {order.accession_number || order.id.slice(0, 8)}
                </h2>
                <p className="text-xs text-neu-inkSoft">
                  Liberado em{" "}
                  {new Date(order.completed_at).toLocaleString("pt-BR")}
                </p>
              </div>
              <button
                type="button"
                disabled={downloading === order.id}
                onClick={() => download(order)}
                className="neu-btn-primary inline-flex items-center justify-center gap-2 px-3 py-2 text-sm disabled:opacity-50"
              >
                <Download size={15} />
                {downloading === order.id ? "Baixando…" : "Baixar laudo PDF"}
              </button>
            </header>
            <div className="divide-y divide-neu-app">
              {order.items.map((item) => (
                <div
                  key={item.id}
                  className="grid gap-1 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                >
                  <div>
                    <p className="font-medium text-neu-ink">{item.test_name}</p>
                    <p className="text-xs text-neu-inkSoft">
                      {[
                        item.specimen_type,
                        item.method,
                        item.reference_range &&
                          `Referência: ${item.reference_range}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <p
                    className={
                      item.abnormal_flag === "critical"
                        ? "font-bold text-red-700"
                        : "font-bold text-neu-ink"
                    }
                  >
                    {item.result_value || "Resultado no laudo"} {item.unit}
                    <span className="ml-2 text-xs uppercase">
                      {item.abnormal_flag_display}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          </article>
        ))
      )}
      {!loading && !error && orders.length === 0 && (
        <div className="neu-panel p-10 text-center">
          <FlaskConical className="mx-auto text-neu-inkMuted" />
          <p className="mt-3 font-medium text-neu-ink">Nenhum laudo liberado</p>
          <p className="text-sm text-neu-inkSoft">
            Seus resultados aparecerão aqui após validação e assinatura.
          </p>
        </div>
      )}
    </div>
  );
}
