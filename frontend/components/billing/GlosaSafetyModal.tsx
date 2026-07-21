'use client';

import { useMemo, useState } from 'react';
import { X, AlertTriangle, XCircle, ShieldAlert } from 'lucide-react';
import {
  acknowledgeGlosaAlert,
  type GlosaAlert,
  type GlosaGuideBlock,
  type GlosaSafetyBlock,
} from '@/lib/glosa-safety';

interface GlosaSafetyModalProps {
  block: GlosaSafetyBlock;
  /** Called once EVERY blocking alert is acknowledged — the caller retries the close. */
  onResolved: () => void;
  onClose: () => void;
}

// Mirrors DoseSafetyModal's SEVERITY_STYLES so the two modals look identical.
// glosa severity is "block" (red) or "advise" (amber).
const SEVERITY_STYLES: Record<
  string,
  { bg: string; text: string; border: string; icon: React.ReactNode; label: string }
> = {
  block: {
    bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200',
    icon: <XCircle size={16} />, label: 'Bloqueio',
  },
  advise: {
    bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200',
    icon: <AlertTriangle size={16} />, label: 'Atenção',
  },
};

// check_code → pt-BR label (locked decision in docs/plans/GLOSA-WEDGE.md PR G1).
const CHECK_CODE_LABELS: Record<string, string> = {
  duplicate: 'Procedimento já apresentado (duplicidade)',
  not_in_table: 'Procedimento não tabelado/coberto',
  stale_price: 'Valor diverge da tabela vigente',
  incomplete: 'Dados incompletos',
  engine_error: 'Verificação indisponível',
  table_unresolved: 'Tabela de preços não resolvida',
};

const MIN_REASON = 10;

function checkCodeLabel(code: string): string {
  return CHECK_CODE_LABELS[code] ?? code;
}

function AlertRow({ alert }: { alert: GlosaAlert }) {
  const styles = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.advise;
  return (
    <div className={`rounded-lg border p-3 ${styles.bg} ${styles.border}`}>
      <div className="flex items-start gap-2">
        <span className={styles.text}>{styles.icon}</span>
        <div className="flex-1 min-w-0">
          <span className={`text-xs font-semibold uppercase tracking-wide ${styles.text}`}>
            {checkCodeLabel(alert.check_code)}
          </span>
          <p className={`text-sm font-medium mt-0.5 ${styles.text}`}>{alert.message}</p>
          {alert.recommendation && (
            <p className="text-xs text-neu-inkSoft mt-1">{alert.recommendation}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function GuideSection({
  guide,
  reason,
  onReasonChange,
  error,
}: {
  guide: GlosaGuideBlock;
  reason: string;
  onReasonChange: (value: string) => void;
  error: string | null;
}) {
  const blockAlerts = guide.alerts.filter(a => a.severity === 'block');
  const hasBlock = blockAlerts.length > 0;
  // alto if any block alert, médio if only advise.
  const riskBadge = hasBlock
    ? { label: 'Risco alto', cls: 'bg-red-100 text-red-700 border-red-200' }
    : { label: 'Risco médio', cls: 'bg-yellow-100 text-yellow-800 border-yellow-300' };

  return (
    <div className="rounded-xl border border-slate-200 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-neu-ink">
          Guia {guide.guide_number}
        </h3>
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${riskBadge.cls}`}>
          {riskBadge.label}
        </span>
      </div>

      <div className="space-y-2">
        {guide.alerts.map(alert => (
          <AlertRow key={alert.id} alert={alert} />
        ))}
      </div>

      {hasBlock && (
        <div className="space-y-1">
          <label className="block text-xs font-medium text-neu-inkSoft mb-1">
            Motivo para fechar mesmo assim (obrigatório, mín. 10 caracteres) — reconhece{' '}
            {blockAlerts.length === 1 ? 'o bloqueio' : `os ${blockAlerts.length} bloqueios`} desta guia
          </label>
          <textarea
            value={reason}
            onChange={e => onReasonChange(e.target.value)}
            rows={2}
            placeholder="Descreva a justificativa do faturamento..."
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
        </div>
      )}
    </div>
  );
}

export function GlosaSafetyModal({ block, onResolved, onClose }: GlosaSafetyModalProps) {
  // Per-guide reason text (one reason acknowledges ALL block alerts of that guide).
  const [reasons, setReasons] = useState<Record<string, string>>({});
  // Per-guide acknowledge error (mirrors DoseSafetyModal's inline error pattern).
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  // Guides that carry at least one block alert require a justification.
  const blockingGuides = useMemo(
    () => block.guides.filter(g => g.alerts.some(a => a.severity === 'block')),
    [block.guides],
  );

  const allResolved = blockingGuides.every(
    g => (reasons[g.guide_id]?.trim().length ?? 0) >= MIN_REASON,
  );
  const canConfirm = blockingGuides.length > 0 && allResolved;

  const handleConfirm = async () => {
    setSubmitting(true);
    setErrors({});
    try {
      for (const guide of blockingGuides) {
        const reason = (reasons[guide.guide_id] ?? '').trim();
        if (reason.length < MIN_REASON) {
          setErrors(prev => ({
            ...prev,
            [guide.guide_id]: 'O motivo deve ter pelo menos 10 caracteres.',
          }));
          setSubmitting(false);
          return;
        }
        // One reason → acknowledge every block alert of this guide (sequential).
        const blockAlerts = guide.alerts.filter(a => a.severity === 'block');
        for (const alert of blockAlerts) {
          try {
            await acknowledgeGlosaAlert(alert.id, reason);
          } catch (e) {
            setErrors(prev => ({
              ...prev,
              [guide.guide_id]: e instanceof Error ? e.message : 'Erro ao reconhecer alerta.',
            }));
            setSubmitting(false);
            return;
          }
        }
      }
      onResolved();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40">
      <div className="bg-neu-panel rounded-xl shadow-neu-panel w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <span className="text-red-600"><ShieldAlert size={18} /></span>
            <h2 className="text-base font-semibold text-neu-ink">Risco de glosa</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-neu-inkSoft transition-colors"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <p className="text-sm text-neu-inkSoft">{block.detail}</p>

          {block.guides.map(guide => (
            <GuideSection
              key={guide.guide_id}
              guide={guide}
              reason={reasons[guide.guide_id] ?? ''}
              onReasonChange={value => {
                setReasons(prev => ({ ...prev, [guide.guide_id]: value }));
                setErrors(prev => ({ ...prev, [guide.guide_id]: '' }));
              }}
              error={errors[guide.guide_id] || null}
            />
          ))}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-slate-200 space-y-2">
          <button
            onClick={handleConfirm}
            disabled={submitting || !canConfirm}
            className="w-full text-sm font-semibold px-3 py-2.5 rounded-lg bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white hover:shadow-neu-btn-primary-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Reconhecendo...' : 'Reconhecer e fechar o lote'}
          </button>
          <button
            onClick={onClose}
            className="w-full text-sm text-neu-inkSoft hover:text-neu-ink py-1.5 transition-colors"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}
