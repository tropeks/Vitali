'use client';

import { useEffect, useState } from 'react';
import { Bot } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { DPASignModal } from '@/components/settings/DPASignModal';
import { Button, PageShell, StatusBadge, ReadinessPanel } from '@/components/shared';
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
        <p className="text-sm text-neu-inkMuted">Carregando...</p>
      </PageShell>
    );
  }

  return (
    <PageShell variant="operational">
      <div className="max-w-3xl space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Inteligência Artificial</h1>
          <p className="text-sm text-neu-inkSoft mt-1">
            Gerencie o Acordo de Processamento de Dados e as configurações de IA da clínica.
          </p>
        </div>

        <section className="bg-neu-panel rounded-xl shadow-neu-panel border border-white">
          <div className="border-b border-neu-app/50 px-4 py-3 flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-base font-semibold text-neu-ink">
              Acordo de Processamento de Dados (DPA)
            </h2>
            <StatusBadge meta={getDpaStatusMeta(status?.is_signed)} />
          </div>
          <div className="p-4 space-y-4">
            {status?.is_signed ? (
              <div className="space-y-1.5 text-sm text-neu-ink">
                <p>
                  <span className="text-xs font-semibold uppercase tracking-wide text-neu-inkSoft">
                    Data de assinatura
                  </span>{' '}
                  <span className="ml-1">{formatDate(status.signed_at)}</span>
                </p>
                <p>
                  <span className="text-xs font-semibold uppercase tracking-wide text-neu-inkSoft">
                    Assinado por
                  </span>{' '}
                  <span className="ml-1">{status.signed_by_name ?? '—'}</span>
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-neu-ink">
                  Para utilizar os recursos de Inteligência Artificial (incluindo IA Clínica /
                  Scribe), é necessário assinar o Acordo de Processamento de Dados em conformidade
                  com a LGPD.
                </p>
                <div>
                  {canSign ? (
                    <Button
                      variant="primary"
                      onClick={() => setShowModal(true)}
                      className="inline-flex items-center gap-2"
                    >
                      Assinar DPA
                    </Button>
                  ) : (
                    <div className="inline-flex items-center gap-2">
                      <Button
                        variant="primary"
                        disabled
                        title="Apenas administradores podem assinar o DPA"
                        className="inline-flex items-center gap-2"
                      >
                        Assinar DPA
                      </Button>
                      <span className="text-xs text-neu-inkMuted">
                        Apenas administradores podem assinar.
                      </span>
                    </div>
                  )}
                </div>
                {error && <p className="text-sm text-neu-danger">{error}</p>}
              </div>
            )}
          </div>
        </section>

        {status?.is_signed && status?.ai_scribe_enabled && (
          <section className="bg-neu-panel rounded-xl shadow-neu-panel border border-white">
            <div className="border-b border-neu-app/50 px-4 py-3 flex items-center gap-2 flex-wrap">
              <Bot size={18} className="text-neu-brand" />
              <h2 className="text-base font-semibold text-neu-ink">IA Clínica (Scribe)</h2>
              <StatusBadge
                meta={{
                  label: 'Ativo',
                  badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20',
                }}
              />
            </div>
            <div className="p-4">
              <p className="text-sm text-neu-ink">
                O módulo de IA Clínica está habilitado. As transcrições de consultas são
                processadas automaticamente para geração de notas SOAP, com armazenamento
                criptografado em conformidade com a LGPD.
              </p>
            </div>
          </section>
        )}

        {/* ── Prontidão de curadoria de dados ── */}
        <section className="bg-neu-panel rounded-xl shadow-neu-panel border border-white">
          <div className="border-b border-neu-app/50 px-4 py-3">
            <h2 className="text-base font-semibold text-neu-ink">
              Prontidão de curadoria de dados
            </h2>
          </div>
          <div className="p-4 space-y-4">
            {wedges.length === 0 ? (
              <p className="text-sm text-neu-inkMuted">Nenhum dado de prontidão disponível.</p>
            ) : (
              wedges.map((w) => (
                <div key={w.key} className="space-y-1">
                  <ReadinessPanel
                    title={w.label}
                    blockers={w.blockers}
                    readyText={w.ready_text}
                  />
                  <p className="text-xs text-neu-inkMuted pl-1">
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
