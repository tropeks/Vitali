"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  portalApi,
  PortalNotActiveError,
  PortalUnauthorizedError,
} from "@/lib/portal-api";

interface PortalListProps<T> {
  title: string;
  subtitle?: string;
  fetcher: keyof typeof portalApi;
  empty: { title: string; detail: string };
  renderRow: (item: T) => ReactNode;
  rowKey: (item: T) => string;
}

/**
 * Generic list shell for the patient portal — owns loading / unauthorized /
 * not-active redirects so each leaf page only has to declare:
 *
 * - which API method to call (`fetcher` — type-safe lookup on `portalApi`)
 * - how to render one row
 *
 * Mirrors the patient_portal/views.py self-data surface: a 401 means
 * "session expired" → /portal/login; a 403 means "your PatientPortalAccess
 * is not active" → /portal/activate.
 */
export default function PortalList<T>({
  title,
  subtitle,
  fetcher,
  empty,
  renderRow,
  rowKey,
}: PortalListProps<T>) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<T[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = (await (portalApi[fetcher] as () => Promise<T[]>)()) ?? [];
        if (!cancelled) {
          setItems(Array.isArray(data) ? data : []);
          setLoading(false);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof PortalUnauthorizedError) {
          window.location.assign("/portal/login");
          return;
        }
        if (err instanceof PortalNotActiveError) {
          window.location.assign("/portal/activate");
          return;
        }
        setError("Não foi possível carregar as informações. Tente novamente.");
        setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [fetcher]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
      </div>

      {loading && <p className="text-sm text-slate-500">Carregando…</p>}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-6 text-center">
          <p className="text-sm font-semibold text-slate-900">{empty.title}</p>
          <p className="mt-1 text-xs text-slate-500">{empty.detail}</p>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={rowKey(item)}
              className="rounded-lg border border-slate-200 bg-white p-4"
            >
              {renderRow(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
