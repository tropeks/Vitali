'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';
import { Loader2, ShieldCheck, AlertTriangle, XCircle } from 'lucide-react';

export interface SafetyAlert {
  id: string;
  alert_type: string;
  severity: string;
  message: string;
  recommendation: string;
  status: string;
  acknowledged_at: string | null;
}

export interface SafetyStatus {
  status: 'pending' | 'safe' | 'warning' | 'contraindication' | 'flagged' | 'error';
  alerts: SafetyAlert[];
}

interface SafetyBadgeProps {
  prescriptionId: string;
  itemId: string;
  /** Called when badge is clicked and there are alerts to show */
  onAlertsClick?: (alerts: SafetyAlert[]) => void;
}

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 5; // 10s total

async function fetchSafetyStatus(prescriptionId: string, itemId: string): Promise<SafetyStatus> {
  const token = getAccessToken();
  const res = await fetch(
    `/api/v1/prescription-items/${itemId}/safety-check/`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) return { status: 'error', alerts: [] };
  return res.json();
}

export function SafetyBadge({ prescriptionId, itemId, onAlertsClick }: SafetyBadgeProps) {
  const [safetyStatus, setSafetyStatus] = useState<SafetyStatus>({ status: 'pending', alerts: [] });
  const pollCount = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async () => {
    const result = await fetchSafetyStatus(prescriptionId, itemId);
    setSafetyStatus(result);

    pollCount.current += 1;
    const isDone = result.status !== 'pending' || pollCount.current >= MAX_POLLS;

    if (!isDone) {
      timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    }
  }, [prescriptionId, itemId]);

  useEffect(() => {
    pollCount.current = 0;
    timerRef.current = setTimeout(poll, 0);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [poll]);

  const { status, alerts } = safetyStatus;
  const hasActiveAlerts = alerts.some(a => a.status === 'flagged');
  const isClickable = (status === 'warning' || status === 'contraindication' || (status === 'flagged' && hasActiveAlerts));

  const handleClick = () => {
    if (isClickable && onAlertsClick) {
      onAlertsClick(alerts);
    }
  };

  if (status === 'pending') {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-500"
        role="status"
        aria-label="Verificação de segurança em andamento"
      >
        <Loader2 size={11} className="animate-spin" />
        Verificando...
      </span>
    );
  }

  if (status === 'safe') {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700"
        role="status"
        aria-label="Verificação de segurança: Seguro"
      >
        <ShieldCheck size={11} />
        Seguro
      </span>
    );
  }

  if (status === 'warning' || (status === 'flagged' && !alerts.some(a => a.severity === 'contraindication'))) {
    return (
      <button
        onClick={handleClick}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-50 text-yellow-700 hover:bg-yellow-100 transition-colors cursor-pointer"
        role="status"
        aria-label="Verificação de segurança: Atenção — clique para detalhes"
        title="Clique para ver alertas"
      >
        <AlertTriangle size={11} />
        Atenção
      </button>
    );
  }

  if (status === 'contraindication' || (status === 'flagged' && alerts.some(a => a.severity === 'contraindication'))) {
    return (
      <button
        onClick={handleClick}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700 hover:bg-red-100 transition-colors cursor-pointer"
        role="status"
        aria-label="Verificação de segurança: Contraindicado — clique para detalhes"
        title="Clique para ver alertas"
      >
        <XCircle size={11} />
        Contraindicado
      </button>
    );
  }

  // error / unknown
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-500"
      role="status"
      aria-label="Verificar manualmente"
    >
      Verificar manualmente
    </span>
  );
}
