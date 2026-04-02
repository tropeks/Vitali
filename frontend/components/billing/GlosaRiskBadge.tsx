'use client';

/**
 * GlosaRiskBadge — S-034 Glosa Prediction
 *
 * Fetches glosa risk for a single procedure item when tussCode + insurerAnsCode
 * are both known. Shows a risk pill (low / medium / high) with a tooltip explaining
 * the reason. Returns prediction_id via onPrediction so the parent can include
 * it in the guide submit body.
 *
 * States: idle → loading (shimmer) → low | medium | high | degraded
 */

import { useState, useEffect, useRef } from 'react';
import { getAccessToken } from '@/lib/auth';

export interface GlosaPrediction {
  prediction_id: string | null;
  risk_level: 'low' | 'medium' | 'high';
  risk_reason: string;
  risk_code: string;
  degraded: boolean;
  cached: boolean;
}

interface Props {
  tussCode: string | null;
  insurerAnsCode: string | null;
  insurerName?: string;
  cid10Codes?: string[];
  guideType: string;
  onPrediction?: (predictionId: string | null) => void;
}

type State =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'result'; data: GlosaPrediction }
  | { kind: 'degraded' };

const RISK_STYLES: Record<string, string> = {
  low: 'bg-green-50 border-green-200 text-green-700',
  medium: 'bg-yellow-50 border-yellow-300 text-yellow-800',
  high: 'bg-red-50 border-red-300 text-red-700',
};

const RISK_LABEL: Record<string, string> = {
  low: 'Risco Baixo',
  medium: 'Risco Médio',
  high: 'Risco Alto',
};

const RISK_ICON: Record<string, string> = {
  low: '✓',
  medium: '⚠',
  high: '✕',
};

export default function GlosaRiskBadge({
  tussCode,
  insurerAnsCode,
  insurerName = '',
  cid10Codes = [],
  guideType,
  onPrediction,
}: Props) {
  const [state, setState] = useState<State>({ kind: 'idle' });
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const reqIdRef = useRef(0);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Need both TUSS code and insurer ANS code to predict
    if (!tussCode || !insurerAnsCode) {
      abortRef.current?.abort();
      setState({ kind: 'idle' });
      onPrediction?.(null);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const reqId = ++reqIdRef.current;

    setState({ kind: 'loading' });

    const token = getAccessToken();
    if (!token) {
      setState({ kind: 'idle' });
      return;
    }

    fetch('/api/v1/ai/glosa-predict/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        tuss_code: tussCode,
        insurer_ans_code: insurerAnsCode,
        insurer_name: insurerName,
        cid10_codes: cid10Codes,
        guide_type: guideType,
      }),
      signal: controller.signal,
    })
      .then(r => r.json())
      .then((data: GlosaPrediction) => {
        if (reqId !== reqIdRef.current) return;
        if (data.degraded) {
          setState({ kind: 'degraded' });
          onPrediction?.(null);
        } else {
          setState({ kind: 'result', data });
          onPrediction?.(data.prediction_id);
        }
      })
      .catch((err: any) => {
        if (err?.name === 'AbortError') return;
        if (reqId !== reqIdRef.current) return;
        setState({ kind: 'degraded' });
        onPrediction?.(null);
      });

    return () => {
      controller.abort();
    };
  // cid10Codes serialized to string so array identity doesn't cause infinite loops
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tussCode, insurerAnsCode, insurerName, guideType, JSON.stringify(cid10Codes)]);

  // Close tooltip on outside click
  useEffect(() => {
    if (!tooltipVisible) return;
    const handler = (e: MouseEvent) => {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target as Node)) {
        setTooltipVisible(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [tooltipVisible]);

  if (state.kind === 'idle') return null;

  if (state.kind === 'loading') {
    return (
      <div className="mt-1 flex items-center gap-1">
        <div className="h-5 w-20 bg-gray-100 rounded-full animate-pulse" />
        <div className="h-5 w-32 bg-gray-100 rounded-full animate-pulse opacity-60" />
      </div>
    );
  }

  if (state.kind === 'degraded') {
    return (
      <div className="mt-1">
        <span className="inline-flex items-center px-2 py-0.5 text-xs border border-gray-200 bg-gray-50 text-gray-400 rounded-full">
          Previsão de glosa indisponível
        </span>
      </div>
    );
  }

  const { data } = state;
  const riskStyle = RISK_STYLES[data.risk_level] ?? RISK_STYLES.low;
  const label = RISK_LABEL[data.risk_level] ?? data.risk_level;
  const icon = RISK_ICON[data.risk_level] ?? '?';

  return (
    <div className="mt-1 relative inline-block" ref={tooltipRef}>
      <button
        type="button"
        onClick={() => setTooltipVisible(v => !v)}
        aria-label={`Glosa: ${label}. Clique para detalhes.`}
        className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium border rounded-full cursor-pointer hover:opacity-80 transition-opacity ${riskStyle}`}
      >
        <span aria-hidden="true">{icon}</span>
        <span>Glosa: {label}</span>
        {data.risk_code && (
          <span className="ml-0.5 font-mono opacity-70">({data.risk_code})</span>
        )}
      </button>

      {tooltipVisible && data.risk_reason && (
        <div
          role="tooltip"
          className="absolute z-50 left-0 top-6 w-64 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-lg"
        >
          <p>{data.risk_reason}</p>
          {data.risk_code && (
            <p className="mt-1 opacity-60 font-mono">Código TISS: {data.risk_code}</p>
          )}
          <div className="absolute -top-1.5 left-3 w-3 h-3 bg-gray-900 rotate-45" />
        </div>
      )}
    </div>
  );
}
