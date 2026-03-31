'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';

export interface TUSSSuggestion {
  tuss_code: string;
  description: string;
  rank: number;
  tuss_code_id: number;
  suggestion_id: string;
}

interface Props {
  description: string;
  guideType?: string;
  onSelect: (suggestion: TUSSSuggestion) => void;
  hasExistingCode: boolean;
}

type State =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'suggestions'; items: TUSSSuggestion[] }
  | { kind: 'empty' }
  | { kind: 'degraded' };

const MIN_DESCRIPTION_LENGTH = 3;
const DEBOUNCE_MS = 600;

export default function TUSSSuggestionInline({ description, guideType = '', onSelect, hasExistingCode }: Props) {
  const [state, setState] = useState<State>({ kind: 'idle' });
  const [pendingSelect, setPendingSelect] = useState<TUSSSuggestion | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const pillsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const fetchSuggestions = useCallback(async (desc: string, reqId: number) => {
    setState({ kind: 'loading' });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = getAccessToken();
      if (!token) {
        setState({ kind: 'idle' });
        return;
      }

      const res = await fetch('/api/v1/ai/tuss-suggest/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ description: desc, guide_type: guideType }),
        signal: controller.signal,
      });

      // Discard stale response if a newer request was made
      if (reqId !== requestIdRef.current) return;

      if (!res.ok) {
        setState({ kind: 'idle' });
        return;
      }

      const data = await res.json();

      if (reqId !== requestIdRef.current) return;

      if (data.degraded) {
        setState({ kind: 'degraded' });
      } else if (!data.suggestions || data.suggestions.length === 0) {
        setState({ kind: 'empty' });
      } else {
        setState({ kind: 'suggestions', items: data.suggestions });
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') return;
      if (reqId !== requestIdRef.current) return;
      setState({ kind: 'degraded' });
    }
  }, [guideType]);

  useEffect(() => {
    if (description.length < MIN_DESCRIPTION_LENGTH) {
      abortRef.current?.abort();
      setState({ kind: 'idle' });
      return;
    }

    // Cancel previous in-flight request
    abortRef.current?.abort();
    const reqId = ++requestIdRef.current;

    const timer = setTimeout(() => {
      fetchSuggestions(description, reqId);
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [description, guideType, fetchSuggestions]);

  const handlePillClick = (suggestion: TUSSSuggestion) => {
    if (hasExistingCode) {
      setPendingSelect(suggestion);
    } else {
      applySelection(suggestion);
    }
  };

  const applySelection = (suggestion: TUSSSuggestion) => {
    onSelect(suggestion);
    setPendingSelect(null);
    setState({ kind: 'idle' });
    // Post feedback (fire and forget)
    postFeedback(suggestion);
  };

  const postFeedback = (suggestion: TUSSSuggestion) => {
    if (!suggestion.suggestion_id) return;
    const token = getAccessToken();
    if (!token) return;
    fetch('/api/v1/ai/tuss-suggest/feedback/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ suggestion_id: suggestion.suggestion_id, accepted: true }),
    }).catch(() => {
      // Fire-and-forget: feedback loss is acceptable, do not surface errors to user.
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent, idx: number, items: TUSSSuggestion[]) => {
    if (e.key === 'ArrowRight' && idx < items.length - 1) {
      e.preventDefault();
      pillsRef.current[idx + 1]?.focus();
    } else if (e.key === 'ArrowLeft' && idx > 0) {
      e.preventDefault();
      pillsRef.current[idx - 1]?.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setState({ kind: 'idle' });
    }
  };

  if (state.kind === 'idle') return null;

  return (
    <div role="status" aria-live="polite" className="mt-1">
      {state.kind === 'loading' && (
        <p className="text-xs text-slate-400 flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 border border-slate-300 border-t-transparent rounded-full animate-spin" />
          Buscando sugestões...
        </p>
      )}

      {state.kind === 'suggestions' && (
        <div className="flex flex-wrap gap-1.5 sm:flex-row flex-col">
          {state.items.map((item, idx) => (
            <button
              key={item.tuss_code}
              ref={el => { pillsRef.current[idx] = el; }}
              type="button"
              onClick={() => handlePillClick(item)}
              onKeyDown={e => handleKeyDown(e, idx, state.items)}
              aria-label={`Selecionar TUSS ${item.tuss_code}: ${item.description}`}
              className="min-h-[44px] sm:min-h-0 px-2.5 py-1 text-xs font-medium border border-blue-300 text-blue-700 bg-blue-50 rounded-full hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors max-w-[200px] sm:max-w-[160px] truncate"
              title={`${item.tuss_code} — ${item.description}`}
            >
              <span className="font-mono">{item.tuss_code}</span>
              <span className="ml-1 font-normal opacity-75 hidden sm:inline">
                {item.description.slice(0, 30)}{item.description.length > 30 ? '…' : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      {state.kind === 'empty' && (
        <p className="text-xs text-slate-400">Nenhuma sugestão encontrada — busque o código manualmente.</p>
      )}

      {state.kind === 'degraded' && (
        <button
          type="button"
          disabled
          className="px-2.5 py-1 text-xs font-medium border border-slate-200 text-slate-400 bg-slate-50 rounded-full cursor-default"
          aria-label="IA indisponível — use busca manual"
        >
          IA indisponível — use busca manual
        </button>
      )}

      {/* Overwrite confirmation */}
      {pendingSelect && (
        <div className="mt-1.5 flex items-center gap-2 text-xs text-slate-600 bg-yellow-50 border border-yellow-200 rounded-lg px-2.5 py-1.5">
          <span>Substituir código selecionado?</span>
          <button
            type="button"
            onClick={() => applySelection(pendingSelect)}
            className="font-medium text-yellow-700 hover:underline"
          >
            Sim
          </button>
          <button
            type="button"
            onClick={() => setPendingSelect(null)}
            className="text-slate-400 hover:underline"
          >
            Não
          </button>
        </div>
      )}
    </div>
  );
}
