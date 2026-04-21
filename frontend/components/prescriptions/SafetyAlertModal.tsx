'use client';

import { useState } from 'react';
import { X, AlertTriangle, XCircle, ShieldAlert } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import type { SafetyAlert } from './SafetyBadge';

interface SafetyAlertModalProps {
  alerts: SafetyAlert[];
  onClose: () => void;
  onAcknowledged?: (alertId: string) => void;
}

const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string; icon: React.ReactNode; label: string }> = {
  contraindication: {
    bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200',
    icon: <XCircle size={16} />, label: 'Contraindicação',
  },
  warning: {
    bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200',
    icon: <AlertTriangle size={16} />, label: 'Atenção',
  },
  info: {
    bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200',
    icon: <ShieldAlert size={16} />, label: 'Informação',
  },
};

async function acknowledgeAlert(alertId: string, reason: string): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1/safety-alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Erro ${res.status}`);
  }
}

function AlertRow({ alert, onAcknowledged }: { alert: SafetyAlert; onAcknowledged?: (id: string) => void }) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(alert.status === 'acknowledged');

  const styles = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.info;
  const isContraindication = alert.severity === 'contraindication';
  const minReason = isContraindication ? 10 : 0;

  const handleAcknowledge = async () => {
    if (isContraindication && reason.trim().length < minReason) {
      setError('Para contraindicações, o motivo deve ter pelo menos 10 caracteres.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await acknowledgeAlert(alert.id, reason.trim());
      setDone(true);
      onAcknowledged?.(alert.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao reconhecer alerta.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${styles.bg} ${styles.border}`}>
      <div className="flex items-start gap-2">
        <span className={styles.text}>{styles.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold uppercase tracking-wide ${styles.text}`}>
              {styles.label}
            </span>
            {done && (
              <span className="text-xs text-green-600 font-medium">✓ Reconhecido</span>
            )}
          </div>
          <p className={`text-sm font-medium mt-0.5 ${styles.text}`}>{alert.message}</p>
          {alert.recommendation && (
            <p className="text-xs text-slate-600 mt-1">{alert.recommendation}</p>
          )}
        </div>
      </div>

      {!done && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              {isContraindication
                ? 'Motivo para prescrever mesmo assim (obrigatório, mín. 10 caracteres)'
                : 'Motivo de reconhecimento (opcional)'}
            </label>
            <textarea
              value={reason}
              onChange={e => { setReason(e.target.value); setError(null); }}
              rows={2}
              placeholder={isContraindication ? 'Descreva a justificativa clínica...' : 'Opcional...'}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
          </div>
          <button
            onClick={handleAcknowledge}
            disabled={submitting || (isContraindication && reason.trim().length < minReason)}
            className="text-xs font-medium px-3 py-1.5 rounded-lg bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Salvando...' : 'Reconhecer Alerta'}
          </button>
        </div>
      )}
    </div>
  );
}

export function SafetyAlertModal({ alerts, onClose, onAcknowledged }: SafetyAlertModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-900">Alertas de Segurança</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Alerts list */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {alerts.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-6">Nenhum alerta ativo.</p>
          ) : (
            alerts.map(alert => (
              <AlertRow key={alert.id} alert={alert} onAcknowledged={onAcknowledged} />
            ))
          )}
        </div>

        <div className="px-5 py-3 border-t border-slate-200">
          <button
            onClick={onClose}
            className="w-full text-sm text-slate-600 hover:text-slate-900 py-2 transition-colors"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
