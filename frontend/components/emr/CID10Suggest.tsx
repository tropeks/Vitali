'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';

interface CID10Suggestion {
  code: string;
  description: string;
  confidence: number;
}

interface CID10SuggestProps {
  encounterId: string;
  value: string;
  onChange: (value: string) => void;
  onCodeSelected?: (code: string) => void;
  placeholder?: string;
  rows?: number;
  readOnly?: boolean;
  /** Currently selected CID-10 principal (for replace-confirm flow) */
  currentCid10?: string;
  onCid10Change?: (code: string) => void;
}

const DEBOUNCE_MS = 1500;
const MIN_CHARS = 20;

export function CID10Suggest({
  encounterId,
  value,
  onChange,
  onCodeSelected,
  placeholder = 'Hipótese diagnóstica...',
  rows = 3,
  readOnly = false,
  currentCid10,
  onCid10Change,
}: CID10SuggestProps) {
  const [suggestions, setSuggestions] = useState<CID10Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingCode, setPendingCode] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchSuggestions = useCallback(async (text: string) => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    setLoading(true);
    try {
      const token = getAccessToken();
      const res = await fetch(`/api/v1/encounters/${encounterId}/cid10-suggest/`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text }),
        signal: abortRef.current.signal,
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setSuggestions(data.suggestions ?? []);
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setSuggestions([]);
    } finally {
      setLoading(false);
    }
  }, [encounterId]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (value.trim().length < MIN_CHARS || readOnly) {
      setSuggestions([]);
      setLoading(false);
      return;
    }

    debounceRef.current = setTimeout(() => {
      fetchSuggestions(value.trim());
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [value, readOnly, fetchSuggestions]);

  // Cleanup on unmount
  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort();
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  const acceptCode = async (code: string) => {
    const token = getAccessToken();
    try {
      await fetch(`/api/v1/encounters/${encounterId}/cid10-accept/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
    } catch {
      // fail-open: code is still applied to the field
    }
    onCid10Change?.(code);
    onCodeSelected?.(code);
    setSuggestions([]);
    setPendingCode(null);
  };

  const handleChipClick = (code: string) => {
    if (currentCid10 && currentCid10 !== code) {
      // Show replace confirm
      setPendingCode(code);
    } else {
      acceptCode(code);
    }
  };

  const confidenceColor = (confidence: number) => {
    if (confidence >= 80) return 'text-green-600';
    if (confidence >= 50) return 'text-yellow-600';
    return 'text-slate-400';
  };

  return (
    <div className="space-y-2">
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        readOnly={readOnly}
        placeholder={readOnly ? '' : placeholder}
        rows={rows}
        className={`w-full border rounded-lg px-3 py-2 text-sm resize-y focus:ring-2 focus:ring-blue-500 outline-none transition-colors ${
          readOnly ? 'bg-gray-50 text-gray-600 cursor-default' : 'bg-white border-slate-200'
        }`}
      />

      {/* Suggestion panel */}
      {!readOnly && (loading || suggestions.length > 0) && (
        <div className="space-y-1.5">
          <p className="text-xs text-slate-500 font-medium">Sugestões CID-10</p>
          {loading ? (
            <div className="flex gap-2">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-7 w-32 bg-slate-100 rounded-full animate-pulse" />
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {suggestions.map(s => (
                <button
                  key={s.code}
                  onClick={() => handleChipClick(s.code)}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 transition-colors"
                  title={s.description}
                >
                  <span className="font-mono font-semibold">{s.code}</span>
                  <span className="text-slate-600 max-w-[160px] truncate">{s.description}</span>
                  <span className={`font-normal ${confidenceColor(s.confidence)}`}>{s.confidence}%</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Replace confirm dialog */}
      {pendingCode && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 space-y-2">
          <p className="text-xs text-yellow-800">
            Substituir <span className="font-mono font-bold">{currentCid10}</span> por{' '}
            <span className="font-mono font-bold">{pendingCode}</span>?
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => acceptCode(pendingCode)}
              className="text-xs px-3 py-1 bg-yellow-700 text-white rounded-lg hover:bg-yellow-800 font-medium"
            >
              Substituir
            </button>
            <button
              onClick={() => setPendingCode(null)}
              className="text-xs px-3 py-1 text-yellow-700 hover:text-yellow-900"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
