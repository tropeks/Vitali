'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';

export interface TUSSOption {
  id: number;
  code: string;
  description: string;
}

interface Props {
  value: TUSSOption | null;
  onChange: (opt: TUSSOption | null) => void;
  placeholder?: string;
  disabled?: boolean;
}

export default function TUSSCodeSearch({ value, onChange, placeholder = 'Buscar código TUSS...', disabled }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TUSSOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const search = useCallback((q: string) => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    const token = getAccessToken();
    if (!token) return;
    setLoading(true);
    fetch(`/api/v1/billing/tuss/?q=${encodeURIComponent(q)}&page_size=20`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        const items: TUSSOption[] = (Array.isArray(data) ? data : data.results ?? []).map((r: any) => ({
          id: r.id,
          code: r.code,
          description: r.description,
        }));
        setResults(items);
        setOpen(items.length > 0);
      })
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, []);

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setQuery(q);
    if (value) onChange(null); // clear selection if user types again
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(q), 300);
  };

  const select = (opt: TUSSOption) => {
    onChange(opt);
    setQuery('');
    setOpen(false);
    setResults([]);
  };

  const clear = () => {
    onChange(null);
    setQuery('');
    setResults([]);
    setOpen(false);
  };

  const displayValue = value ? `${value.code} — ${value.description.slice(0, 60)}` : query;

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <input
          type="text"
          value={displayValue}
          onChange={handleInput}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          placeholder={placeholder}
          disabled={disabled}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 pr-8 text-sm focus:ring-2 focus:ring-blue-500 outline-none disabled:bg-gray-50"
        />
        {(value || query) && !disabled && (
          <button
            type="button"
            onClick={clear}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-lg leading-none"
            tabIndex={-1}
          >
            ×
          </button>
        )}
        {loading && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {open && results.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto text-sm">
          {results.map(opt => (
            <li key={opt.id}>
              <button
                type="button"
                onMouseDown={() => select(opt)}
                className="w-full text-left px-3 py-2 hover:bg-blue-50 focus:bg-blue-50 outline-none"
              >
                <span className="font-mono text-blue-700 mr-2">{opt.code}</span>
                <span className="text-gray-700">{opt.description.slice(0, 80)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
