'use client';

import { useEffect, useState } from 'react';
import { Bot } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { DPASignModal } from '@/components/settings/DPASignModal';
import { PageShell, StatusBadge, ReadinessPanel } from '@/components/shared';
import { getDpaStatusMeta } from '@/lib/operational-ui';

interface DPAStatus {
  is_signed: boolean;
  signed_at: string | null;
  signed_by_name: string | null;
  ai_scribe_enabled: boolean;
  current_user_can_sign: boolean;
}

interface ReadinessWedge {
  key: string;
  label: string;
  total: number;
  ready_count: number;
  blockers: string[];
  ready_text: string;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('pt-BR');
}

export default function AISettingsPage() {
  const [status, setStatus] = useState<DPAStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wedges, setWedges] = useState<ReadinessWedge[]>([]);

  const canSign = status?.current_user_can_sign ?? false;

  async function fetchStatus() {
    const token = getAccessToken();
    try {
      const res = await fetch('/api/v1/settings/dpa/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data: DPAStatus = await res.json();
        setStatus(data);
      }
    } catch {
      // ignore — show empty state
    } finally {
      setLoading(false);
    }
  }

  async function fetchReadiness() {
    const token = getAccessToken();
    try {
      const res = await fetch('/api/v1/pharmacy/curation/readiness/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data: { wedges: ReadinessWedge[] } = await res.json();
        setWedges(data.wedges ?? []);
      }
    } catch {
      // ignore — show nothing
    }
  }

  useEffect(() => {
    fetchStatus();
    fetchReadiness();
  }, []);

  async function handleSign() {
    setSigning(true);
    setError(null);
    const token = getAccessToken();
    try {
      const res = await fetch('/api/v1/settings/dpa/sign/', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data: DPAStatus = await res.json();
        setStatus(data);
        setShowModal(false);
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body?.error?.message ?? `Erro ${res.status}`);
      }
    } catch {
      setError('Falha ao assinar o DPA. Verifique sua conexão.');
    } finally {
      setSigning(false);
    }
  }

  if (loading) {
    return (
      <PageShell variant="operational">
        <p className="text-sm text-slate-500">Carregando...</p>
      </PageShell>
    );
  }

  return (
    <PageShell variant="operational">
      <div className="max-w-3xl space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Inteligência Artificial</h1>
          <p className="text-sm text-slate-500 mt-1">
            Gerencie o Acordo de Processamento de Dados e as configurações de IA da clínica.
          </p>
        </div>

        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-base font-semibold text-slate-900">
              Acordo de Processamento de Dados (DPA)
            </h2>
            <StatusBadge meta={getDpaStatusMeta(status?.is_signed)} />
          </div>
          <div className="p-4 space-y-4">
            {status?.is_signed ? (
              <div className="space-y-1.5 text-sm text-slate-700">
                <p>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Data de assinatura
                  </span>{' '}
                  <span className="ml-1">{formatDate(status.signed_at)}</span>
                </p>
                <p>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Assinado por
                  </span>{' '}
                  <span className="ml-1">{status.signed_by_name ?? '—'}</span>
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-slate-700">
                  Para utilizar os recursos de Inteligência Artificial (incluindo IA Clínica /
                  Scribe), é necessário assinar o Acordo de Processamento de Dados em conformidade
                  com a LGPD.
                </p>
                <div>
                  {canSign ? (
                    <button
                      onClick={() => setShowModal(true)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                    >
                      Assinar DPA
                    </button>
                  ) : (
                    <div className="inline-flex items-center gap-2">
                      <button
                        disabled
                        title="Apenas administradores podem assinar o DPA"
                        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-lg opacity-40 cursor-not-allowed"
                      >
                        Assinar DPA
                      </button>
                      <span className="text-xs text-slate-500">
                        Apenas administradores podem assinar.
                      </span>
                    </div>
                  )}
                </div>
                {error && <p className="text-sm text-red-700">{error}</p>}
              </div>
            )}
          </div>
        </section>

        {status?.is_signed && status?.ai_scribe_enabled && (
          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3 flex items-center gap-2 flex-wrap">
              <Bot size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-slate-900">IA Clínica (Scribe)</h2>
              <StatusBadge
                meta={{
                  label: 'Ativo',
                  badgeClass: 'bg-green-100 text-green-800 border-green-200',
                }}
              />
            </div>
            <div className="p-4">
              <p className="text-sm text-slate-700">
                O módulo de IA Clínica está habilitado. As transcrições de consultas são
                processadas automaticamente para geração de notas SOAP, com armazenamento
                criptografado em conformidade com a LGPD.
              </p>
            </div>
          </section>
        )}

        {/* ── Prontidão de curadoria de dados ── */}
        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3">
            <h2 className="text-base font-semibold text-slate-900">
              Prontidão de curadoria de dados
            </h2>
          </div>
          <div className="p-4 space-y-4">
            {wedges.length === 0 ? (
              <p className="text-sm text-slate-500">Nenhum dado de prontidão disponível.</p>
            ) : (
              wedges.map((w) => (
                <div key={w.key} className="space-y-1">
                  <ReadinessPanel
                    title={w.label}
                    blockers={w.blockers}
                    readyText={w.ready_text}
                  />
                  <p className="text-xs text-slate-500 pl-1">
                    {w.ready_count}/{w.total} prontos
                  </p>
                </div>
              ))
            )}
          </div>
        </section>

        {showModal && (
          <DPASignModal
            onConfirm={handleSign}
            onClose={() => {
              setShowModal(false);
              setError(null);
            }}
            loading={signing}
          />
        )}
      </div>
    </PageShell>
  );
}
