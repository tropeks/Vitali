'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, ExternalLink } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { PageShell, KpiTile, SectionState, StatusBadge } from '@/components/shared';
import { SUBSCRIPTION_STATUS_META, resolveBadgeMeta } from '@/lib/operational-ui';

interface Subscription {
  plan_name: string;
  status: 'active' | 'past_due' | 'cancelled' | string;
  monthly_price: number;
  current_period_end: string | null;
  active_modules: string[];
}

function formatCurrency(value: number): string {
  return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('pt-BR');
}

function EmptyState() {
  return (
    <PageShell variant="operational">
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-5 text-center px-4">
        <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center">
          <AlertCircle size={32} className="text-slate-400" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Nenhuma assinatura ativa</h1>
          <p className="text-slate-500 text-sm mt-2 max-w-md">
            Sua conta ainda não possui um plano ativo. Entre em contato para configurar sua
            assinatura.
          </p>
        </div>
        <a
          href="https://calendly.com/vitali-saude"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 transition-colors"
        >
          Agendar conversa
          <ExternalLink size={14} />
        </a>
      </div>
    </PageShell>
  );
}

export default function AssinaturaPage() {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    async function load() {
      const token = getAccessToken();
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const res = await fetch('/api/v1/core/subscription/', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 404) {
          setNotFound(true);
          return;
        }
        if (!res.ok) return;
        const data = await res.json();
        setSubscription(data);
      } catch {
        // leave as null — page will show empty state
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <PageShell variant="operational">
        <div className="space-y-5 animate-pulse">
          <div className="h-8 bg-slate-100 rounded w-48" />
          <div className="grid md:grid-cols-2 gap-4">
            <div className="h-40 bg-slate-100 rounded-lg" />
            <div className="h-40 bg-slate-100 rounded-lg" />
          </div>
        </div>
      </PageShell>
    );
  }

  if (notFound || !subscription) {
    return <EmptyState />;
  }

  const statusMeta = resolveBadgeMeta(SUBSCRIPTION_STATUS_META, subscription.status);
  const isPastDue = subscription.status === 'past_due';
  const isActive = subscription.status === 'active';

  return (
    <PageShell variant="operational">
      <div className="max-w-3xl space-y-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{subscription.plan_name}</h1>
            <p className="text-slate-500 text-sm mt-1">Informações da sua assinatura Vitali</p>
          </div>
          <StatusBadge meta={statusMeta} />
        </div>

        {isPastDue && (
          <SectionState
            title="Pagamento em atraso"
            detail="Regularize seu pagamento para manter o acesso a todos os recursos."
            tone="critical"
            action={
              <a
                href="https://pay.vitali-saude.com.br/regularizar"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-4 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 transition-colors"
              >
                Regularizar pagamento
              </a>
            }
          />
        )}

        <div className="grid md:grid-cols-2 gap-4">
          <KpiTile
            label="Cobrança mensal"
            value={formatCurrency(subscription.monthly_price)}
            hint={`Próxima cobrança em ${formatDate(subscription.current_period_end)}`}
          />
          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3">
              <h2 className="text-base font-semibold text-slate-900">Módulos ativos</h2>
            </div>
            <div className="p-4">
              {subscription.active_modules.length === 0 ? (
                <p className="text-sm text-slate-500">Nenhum módulo ativo.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {subscription.active_modules.map((mod) => (
                    <StatusBadge
                      key={mod}
                      meta={{
                        label: mod,
                        badgeClass: 'bg-green-100 text-green-800 border-green-200',
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>

        {isActive && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-blue-800">Precisa de um módulo adicional?</p>
            <a
              href="https://calendly.com/vitali-saude/modulos"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-semibold text-blue-700 hover:underline inline-flex items-center gap-1"
            >
              Agendar conversa
              <span aria-hidden="true"> →</span>
            </a>
          </div>
        )}

        {!isActive && !isPastDue && (
          <SectionState
            title="Assinatura inativa"
            detail="Entre em contato para reativar seu plano."
          />
        )}
      </div>
    </PageShell>
  );
}
