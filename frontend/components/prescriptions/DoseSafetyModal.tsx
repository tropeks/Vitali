'use client';

import { useMemo, useState } from 'react';
import { X, AlertTriangle, XCircle, ShieldAlert, Scale } from 'lucide-react';
import {
  acknowledgeDoseAlert,
  isWeightGate,
  type DoseAlert,
  type DoseSafetyBlock,
} from '@/lib/dose-safety';

interface DoseSafetyModalProps {
  block: DoseSafetyBlock;
  patientId: string;
  /** Called once EVERY alert is resolved — the caller retries the dispense. */
  onResolved: () => void;
  onClose: () => void;
}

// Mirrors SafetyAlertModal's SEVERITY_STYLES so the two modals look identical.
const SEVERITY_STYLES: Record<
  string,
  { bg: string; text: string; border: string; icon: React.ReactNode; label: string }
> = {
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

const MIN_REASON = 10;

/**
 * Weight-gate handling decision (PR C/3):
 *
 * VitalSigns is a OneToOne on Encounter (apps/emr/models.py::VitalSigns) and is
 * PATCHed at /vital-signs/{id}/. There is NO patient-level weight endpoint. The
 * dispense context only carries `patientId` + a prescription item; it never
 * loads an encounter or a vital_signs id, and a dispense may target a closed
 * encounter. So a VitalSigns id is NOT cleanly resolvable here without inventing
 * an endpoint or making fragile assumptions about the patient's "open"
 * encounter. Per the spec, we therefore surface a clear instruction and a button
 * that only calls onClose() — we do NOT invent an endpoint or guess an id.
 */
function WeightGateRow({ alert }: { alert: DoseAlert }) {
  const styles = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.info;
  return (
    <div className={`rounded-lg border p-4 space-y-3 ${styles.bg} ${styles.border}`}>
      <div className="flex items-start gap-2">
        <span className={styles.text}><Scale size={16} /></span>
        <div className="flex-1 min-w-0">
          <span className={`text-xs font-semibold uppercase tracking-wide ${styles.text}`}>
            Peso necessário
          </span>
          <p className={`text-sm font-medium mt-0.5 ${styles.text}`}>{alert.message}</p>
          <p className="text-xs text-slate-600 mt-1">{alert.recommendation}</p>
        </div>
      </div>
      <p className="text-xs text-slate-700">
        Registre o peso do paciente no atendimento e tente novamente.
      </p>
    </div>
  );
}

function ContraindicationRow({
  alert,
  reason,
  onReasonChange,
  acknowledged,
  error,
}: {
  alert: DoseAlert;
  reason: string;
  onReasonChange: (value: string) => void;
  acknowledged: boolean;
  error: string | null;
}) {
  const styles = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.info;
  const isContraindication = alert.severity === 'contraindication';

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${styles.bg} ${styles.border}`}>
      <div className="flex items-start gap-2">
        <span className={styles.text}>{styles.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold uppercase tracking-wide ${styles.text}`}>
              {styles.label}
            </span>
            {acknowledged && (
              <span className="text-xs text-green-600 font-medium">✓ Reconhecido</span>
            )}
          </div>
          <p className={`text-sm font-medium mt-0.5 ${styles.text}`}>{alert.message}</p>
          {alert.recommendation && (
            <p className="text-xs text-slate-600 mt-1">{alert.recommendation}</p>
          )}
        </div>
      </div>

      {!acknowledged && (
        <div className="space-y-1">
          <label className="block text-xs font-medium text-slate-700 mb-1">
            {isContraindication
              ? 'Motivo para dispensar mesmo assim (obrigatório, mín. 10 caracteres)'
              : 'Motivo de reconhecimento (opcional)'}
          </label>
          <textarea
            value={reason}
            onChange={e => onReasonChange(e.target.value)}
            rows={2}
            placeholder={isContraindication ? 'Descreva a justificativa clínica...' : 'Opcional...'}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
        </div>
      )}
    </div>
  );
}

export function DoseSafetyModal({ block, patientId, onResolved, onClose }: DoseSafetyModalProps) {
  void patientId; // weight-gate is resolved out-of-band (see WeightGateRow comment)

  // Per-alert reason text for contraindication-style alerts.
  const [reasons, setReasons] = useState<Record<string, string>>({});
  // Per-alert acknowledge error (mirrors existing inline error pattern).
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const weightGates = useMemo(() => block.alerts.filter(isWeightGate), [block.alerts]);
  const ackAlerts = useMemo(
    () => block.alerts.filter(a => !isWeightGate(a)),
    [block.alerts],
  );
  const hasWeightGate = weightGates.length > 0;

  // Already-acknowledged alerts (status from backend) need no further action.
  const isPreAcknowledged = (a: DoseAlert) => a.status === 'acknowledged';

  const allAckResolved = ackAlerts.every(
    a => isPreAcknowledged(a) || (reasons[a.id]?.trim().length ?? 0) >= MIN_REASON,
  );
  // Weight gates can only be resolved out-of-band → block the primary action.
  const canConfirm = !hasWeightGate && allAckResolved && ackAlerts.length > 0;

  const handleConfirm = async () => {
    setSubmitting(true);
    setErrors({});
    try {
      for (const alert of ackAlerts) {
        if (isPreAcknowledged(alert)) continue;
        const reason = (reasons[alert.id] ?? '').trim();
        if (reason.length < MIN_REASON) {
          setErrors(prev => ({
            ...prev,
            [alert.id]: 'Para contraindicações, o motivo deve ter pelo menos 10 caracteres.',
          }));
          setSubmitting(false);
          return;
        }
        try {
          await acknowledgeDoseAlert(alert.id, reason);
        } catch (e) {
          setErrors(prev => ({
            ...prev,
            [alert.id]: e instanceof Error ? e.message : 'Erro ao reconhecer alerta.',
          }));
          setSubmitting(false);
          return;
        }
      }
      onResolved();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <span className="text-red-600"><XCircle size={18} /></span>
            <h2 className="text-base font-semibold text-slate-900">Verificação de dose</h2>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          <p className="text-sm text-slate-700">{block.detail}</p>

          {weightGates.map(alert => (
            <WeightGateRow key={alert.id} alert={alert} />
          ))}

          {ackAlerts.map(alert => (
            <ContraindicationRow
              key={alert.id}
              alert={alert}
              reason={reasons[alert.id] ?? ''}
              onReasonChange={value => {
                setReasons(prev => ({ ...prev, [alert.id]: value }));
                setErrors(prev => ({ ...prev, [alert.id]: '' }));
              }}
              acknowledged={isPreAcknowledged(alert)}
              error={errors[alert.id] || null}
            />
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-slate-200 space-y-2">
          {hasWeightGate ? (
            <button
              onClick={onClose}
              className="w-full text-sm font-semibold px-3 py-2.5 rounded-lg bg-slate-800 text-white hover:bg-slate-700 transition-colors"
            >
              Entendi, registrar peso
            </button>
          ) : (
            <button
              onClick={handleConfirm}
              disabled={submitting || !canConfirm}
              className="w-full text-sm font-semibold px-3 py-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Reconhecendo...' : 'Reconhecer e dispensar'}
            </button>
          )}
          <button
            onClick={onClose}
            className="w-full text-sm text-slate-600 hover:text-slate-900 py-1.5 transition-colors"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  );
}
