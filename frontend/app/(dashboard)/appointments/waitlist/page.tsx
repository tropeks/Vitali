"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, ClockIcon, BellRing, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { getAccessToken } from "@/lib/auth";

interface WaitlistEntry {
  id: string;
  patient_name: string | null;
  professional_name: string | null;
  preferred_date_from: string;
  preferred_date_to: string;
  preferred_time_start: string | null;
  preferred_time_end: string | null;
  status: string;
  status_display: string;
  notified_at: string | null;
  expires_at: string | null;
  priority: number;
  created_at: string;
}

interface PageData {
  results: WaitlistEntry[];
  count: number;
  next: string | null;
  previous: string | null;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
  waiting: {
    bg: "bg-slate-100",
    text: "text-slate-600",
    icon: <ClockIcon size={12} />,
  },
  notified: {
    bg: "bg-blue-50",
    text: "text-blue-700",
    icon: <BellRing size={12} />,
  },
  booked: {
    bg: "bg-green-50",
    text: "text-green-700",
    icon: <CheckCircle2 size={12} />,
  },
  expired: {
    bg: "bg-gray-100",
    text: "text-gray-500",
    icon: <XCircle size={12} />,
  },
  cancelled: {
    bg: "bg-red-50",
    text: "text-red-600",
    icon: <XCircle size={12} />,
  },
};

function StatusBadge({ status, label }: { status: string; label: string }) {
  const styles = STATUS_STYLES[status] ?? STATUS_STYLES.waiting;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${styles.bg} ${styles.text}`}
    >
      {styles.icon}
      {label}
    </span>
  );
}

function formatDateRange(from: string, to: string): string {
  const fmtDate = (d: string) =>
    new Date(d + "T00:00:00").toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
    });
  if (from === to) return fmtDate(from);
  return `${fmtDate(from)} — ${fmtDate(to)}`;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options?.body ? { "Content-Type": "application/json" } : {}),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Erro ${res.status}`);
  }
  if (res.status === 204) return {} as T;
  return res.json();
}

export default function WaitlistPage() {
  const [entries, setEntries] = useState<WaitlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await apiFetch<WaitlistEntry[] | PageData>("/waitlist/");
      if (Array.isArray(data)) {
        setEntries(data);
      } else {
        setEntries((data as PageData).results ?? []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar lista de espera.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const cancelEntry = async (id: string) => {
    if (!confirm("Cancelar esta entrada na lista de espera?")) return;
    setCancelling(id);
    setError(null);
    try {
      await apiFetch(`/waitlist/${id}/`, { method: "DELETE" });
      setEntries(prev => prev.map(e => e.id === id ? { ...e, status: "cancelled", status_display: "Cancelado" } : e));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao cancelar.");
    } finally {
      setCancelling(null);
    }
  };

  const activeEntries = entries.filter(e => ["waiting", "notified", "expired"].includes(e.status));
  const otherEntries = entries.filter(e => !["waiting", "notified", "expired"].includes(e.status));

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Lista de Espera</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Pacientes aguardando disponibilidade de horário
          </p>
        </div>
        <span className="text-xs text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
          {activeEntries.length} aguardando
        </span>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
          <AlertTriangle className="text-red-500 shrink-0" size={16} />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 flex items-center justify-center">
          <Loader2 className="animate-spin text-slate-300" size={32} />
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center space-y-2">
          <ClockIcon className="mx-auto text-slate-300" size={40} />
          <p className="text-slate-500 text-sm font-medium">Nenhum paciente na lista de espera.</p>
          <p className="text-xs text-slate-400">
            Quando um horário não estiver disponível, o botão "Entrar na fila de espera" aparecerá no agendamento.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Active entries */}
          {activeEntries.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100">
                <h2 className="text-sm font-semibold text-slate-700">Em andamento</h2>
              </div>
              <div className="divide-y divide-slate-100">
                {activeEntries.map(entry => (
                  <div key={entry.id} className="px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-sm font-medium text-slate-900 truncate">
                        {entry.patient_name ?? "—"}
                      </p>
                      <p className="text-xs text-slate-500 truncate">
                        {entry.professional_name ?? "Qualquer profissional"}
                      </p>
                    </div>

                    <div className="text-xs text-slate-500 shrink-0">
                      {formatDateRange(entry.preferred_date_from, entry.preferred_date_to)}
                    </div>

                    <StatusBadge status={entry.status} label={entry.status_display} />

                    {entry.expires_at && entry.status === "notified" && (
                      <span className="text-xs text-slate-400">
                        Expira {new Date(entry.expires_at).toLocaleDateString("pt-BR")}
                      </span>
                    )}

                    {(entry.status === "waiting" || entry.status === "notified") && (
                      <button
                        onClick={() => cancelEntry(entry.id)}
                        disabled={cancelling === entry.id}
                        className="text-xs text-red-600 hover:text-red-800 font-medium disabled:opacity-40 transition-colors shrink-0"
                      >
                        {cancelling === entry.id ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          "Cancelar"
                        )}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Historical entries */}
          {otherEntries.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100">
                <h2 className="text-sm font-semibold text-slate-700 text-slate-400">Histórico</h2>
              </div>
              <div className="divide-y divide-slate-100">
                {otherEntries.map(entry => (
                  <div key={entry.id} className="px-4 py-3 flex items-center justify-between gap-4 flex-wrap opacity-60">
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-sm font-medium text-slate-700 truncate">
                        {entry.patient_name ?? "—"}
                      </p>
                      <p className="text-xs text-slate-400 truncate">
                        {entry.professional_name ?? "Qualquer profissional"}
                      </p>
                    </div>
                    <div className="text-xs text-slate-400">
                      {formatDateRange(entry.preferred_date_from, entry.preferred_date_to)}
                    </div>
                    <StatusBadge status={entry.status} label={entry.status_display} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
