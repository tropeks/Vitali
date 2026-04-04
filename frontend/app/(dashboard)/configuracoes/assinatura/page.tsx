'use client';

import { useEffect, useState } from 'react';
import { getAccessToken } from '@/lib/auth';
import { AlertCircle, CheckCircle, AlertTriangle, ExternalLink } from 'lucide-react';

interface Subscription {
  plan_name: string;
  status: 'active' | 'past_due' | 'cancelled' | string;
  monthly_price: number;
  current_period_end: string | null;
  active_modules: string[];
}

const STATUS_MAP: Record<string, { label: string; color: string; bg: string; border: string }> = {
  active: {
    label: 'Ativo',
    color: 'text-green-700',
    bg: 'bg-green-100',
    border: 'border-green-200',
  },
  past_due: {
    label: 'Em atraso',
    color: 'text-red-700',
    bg: 'bg-red-100',
    border: 'border-red-200',
  },
  cancelled: {
    label: 'Cancelado',
    color: 'text-slate-600',
    bg: 'bg-slate-100',
    border: 'border-slate-200',
  },
};

function getStatusMeta(status: string) {
  return (
    STATUS_MAP[status] ?? {
      label: status,
      color: 'text-slate-600',
      bg: 'bg-slate-100',
      border: 'border-slate-200',
    }
  );
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
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-5 text-center px-4">
      <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center">
        <AlertCircle size={32} className="text-slate-400" />
      </div>
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Nenhuma assinatura ativa</h2>
        <p className="text-slate-500 text-sm mt-2">
          Sua conta ainda não possui um plano ativo. Entre em contato para configurar sua assinatura.
        </p>
      </div>
      <a
        href="https://calendly.com/vitali-saude"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
      >
        Agendar conversa
        <ExternalLink size={14} />
      </a>
    </div>
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
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-48" />
        <div className="grid md:grid-cols-2 gap-6">
          <div className="h-40 bg-slate-200 rounded-xl" />
          <div className="h-40 bg-slate-200 rounded-xl" />
        </div>
      </div>
    );
  }

  if (notFound || !subscription) {
    return <EmptyState />;
  }

  const statusMeta = getStatusMeta(subscription.status);
  const isPastDue = subscription.status === 'past_due';
  const isActive = subscription.status === 'active';

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{subscription.plan_name}</h1>
          <p className="text-slate-500 text-sm mt-1">Informações da sua assinatura Vitali</p>
        </div>
        {/* Status badge — dominant */}
        <span
          className={`inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold border ${statusMeta.bg} ${statusMeta.color} ${statusMeta.border}`}
        >
          {subscription.status === 'active' && <CheckCircle size={14} />}
          {subscription.status === 'past_due' && <AlertTriangle size={14} />}
          {subscription.status === 'cancelled' && <AlertCircle size={14} />}
          {statusMeta.label}
        </span>
      </div>

      {/* Warning banner for past_due */}
      {isPastDue && (
        <div className="flex items-center justify-between gap-4 flex-wrap bg-red-50 border border-red-200 rounded-xl px-5 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle size={20} className="text-red-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-red-800">Pagamento em atraso</p>
              <p className="text-sm text-red-700 mt-0.5">
                Regularize seu pagamento para manter o acesso a todos os recursos.
              </p>
            </div>
          </div>
          <a
            href="https://pay.vitali-saude.com.br/regularizar"
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
          >
            Regularizar pagamento
          </a>
        </div>
      )}

      {/* KPI grid */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Card 1: Price + Next billing */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-medium text-slate-500 uppercase tracking-wide">
            Cobrança mensal
          </h2>
          <div>
            <p className="text-2xl font-bold text-blue-600">
              {formatCurrency(subscription.monthly_price)}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">por mês</p>
          </div>
          <div>
            <p className="text-xs text-slate-500 font-medium">Próxima cobrança</p>
            <p className="text-sm text-slate-800 font-semibold mt-0.5">
              {formatDate(subscription.current_period_end)}
            </p>
          </div>
        </div>

        {/* Card 2: Active modules */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm space-y-4">
          <h2 className="text-sm font-medium text-slate-500 uppercase tracking-wide">
            Módulos ativos
          </h2>
          {subscription.active_modules.length === 0 ? (
            <p className="text-sm text-slate-400">Nenhum módulo ativo.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {subscription.active_modules.map((mod) => (
                <span
                  key={mod}
                  className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-green-100 text-green-700 gap-1"
                >
                  <span aria-hidden="true">✓</span>
                  {mod}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Upsell CTA for active plans */}
      {isActive && (
        <div className="flex items-center justify-between gap-4 flex-wrap bg-blue-50 border border-blue-200 rounded-xl px-5 py-4">
          <p className="text-sm text-blue-800">
            Precisa de um módulo adicional?
          </p>
          <a
            href="https://calendly.com/vitali-saude/modulos"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-blue-700 hover:underline inline-flex items-center gap-1"
          >
            Agendar conversa
            <span aria-hidden="true"> →</span>
          </a>
        </div>
      )}
    </div>
  );
}
