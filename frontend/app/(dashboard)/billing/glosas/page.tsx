'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

const APPEAL_BADGE: Record<string, string> = {
  none: 'bg-[#DFE5EB] text-[#57606A]',
  pending: 'bg-yellow-100 text-yellow-700',
  accepted: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
};

const APPEAL_LABEL: Record<string, string> = {
  none: 'Sem Recurso',
  pending: 'Recurso Pendente',
  accepted: 'Recurso Aceito',
  rejected: 'Recurso Negado',
};

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export default function GlosasPage() {
  const router = useRouter();
  const [glosas, setGlosas] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [appealModal, setAppealModal] = useState<{ id: string; guideNumber: string } | null>(null);
  const [appealText, setAppealText] = useState('');
  const [submittingAppeal, setSubmittingAppeal] = useState(false);
  const [appealError, setAppealError] = useState('');

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    fetch('/api/v1/billing/glosas/', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then(data => setGlosas(Array.isArray(data) ? data : data.results ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const submitAppeal = async () => {
    if (!appealModal) return;
    if (!appealText.trim()) { setAppealError('O texto do recurso é obrigatório.'); return; }
    const token = getAccessToken();
    if (!token) { setAppealError('Sessão expirada'); return; }
    setSubmittingAppeal(true);
    setAppealError('');
    try {
      const res = await fetch(`/api/v1/billing/glosas/${appealModal.id}/appeal/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ appeal_text: appealText }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `${res.status}`);
      }
      const updated = await res.json();
      setGlosas(prev => prev.map(g => g.id === appealModal.id ? { ...g, ...updated } : g));
      setAppealModal(null);
      setAppealText('');
    } catch (e: any) {
      setAppealError(e.message);
    } finally {
      setSubmittingAppeal(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#24292F]">Glosas</h1>
        <p className="text-sm text-[#8C959F] mt-1">{glosas.length} glosa{glosas.length !== 1 ? 's' : ''}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      <div className="bg-[#F4F7FA] rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#F4F7FA] border-b border-slate-100">
            <tr>
              {['Guia', 'Paciente', 'Motivo', 'Valor Glosado', 'Status Recurso', ''].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-[#8C959F] uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-[#DFE5EB] rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : glosas.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400">
                  Nenhuma glosa encontrada
                </td>
              </tr>
            ) : glosas.map(g => (
              <tr key={g.id} className="hover:bg-[#F4F7FA] transition-colors">
                <td className="px-4 py-3">
                  <button
                    onClick={() => g.guide_id && router.push(`/billing/guides/${g.guide_id}`)}
                    className="font-mono text-[#0066A1] hover:underline text-xs"
                  >
                    {g.guide_number ?? g.guide ?? '—'}
                  </button>
                </td>
                <td className="px-4 py-3 text-[#24292F]">{g.patient_name ?? g.patient ?? '—'}</td>
                <td className="px-4 py-3 text-[#57606A] max-w-xs">
                  <span className="line-clamp-2">{g.reason ?? g.motivo ?? '—'}</span>
                </td>
                <td className="px-4 py-3 text-red-600 font-medium">{fmtCurrency(g.value ?? g.valor_glosado)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${APPEAL_BADGE[g.appeal_status ?? 'none'] ?? 'bg-[#DFE5EB] text-[#57606A]'}`}>
                    {APPEAL_LABEL[g.appeal_status ?? 'none'] ?? g.appeal_status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {(!g.appeal_status || g.appeal_status === 'none') && (
                    <button
                      onClick={() => { setAppealModal({ id: g.id, guideNumber: g.guide_number ?? g.guide ?? g.id }); setAppealText(''); setAppealError(''); }}
                      className="text-orange-600 hover:underline text-xs font-medium"
                    >
                      Recorrer
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Appeal modal */}
      {appealModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-[#F4F7FA] rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] w-full max-w-md p-4 space-y-4">
            <h2 className="text-lg font-semibold text-[#24292F]">Recurso — Guia {appealModal.guideNumber}</h2>
            {appealError && (
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">{appealError}</div>
            )}
            <div>
              <label className="block text-sm font-medium text-[#57606A] mb-1">Justificativa do Recurso *</label>
              <textarea
                value={appealText}
                onChange={e => setAppealText(e.target.value)}
                rows={4}
                placeholder="Descreva a justificativa para o recurso..."
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 outline-none"
              />
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <button
                onClick={() => { setAppealModal(null); setAppealText(''); }}
                className="px-4 py-2 text-sm text-[#57606A] hover:text-slate-800"
              >
                Cancelar
              </button>
              <button
                onClick={submitAppeal}
                disabled={!appealText.trim() || submittingAppeal}
                className="bg-orange-500 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submittingAppeal ? 'Enviando...' : 'Enviar Recurso'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
