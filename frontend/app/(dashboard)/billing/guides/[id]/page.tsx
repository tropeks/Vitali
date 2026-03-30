'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  pending: 'bg-yellow-100 text-yellow-700',
  submitted: 'bg-blue-100 text-blue-700',
  paid: 'bg-green-100 text-green-700',
  denied: 'bg-red-100 text-red-700',
  appeal: 'bg-orange-100 text-orange-700',
};

const STATUS_LABEL: Record<string, string> = {
  draft: 'Rascunho',
  pending: 'Pendente',
  submitted: 'Enviado',
  paid: 'Pago',
  denied: 'Glosado',
  appeal: 'Recurso',
};

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900">{value ?? '—'}</dd>
    </div>
  );
}

export default function GuideDetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;

  const [guide, setGuide] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [actionMsg, setActionMsg] = useState('');

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    fetch(`/api/v1/billing/guides/${id}/`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then(setGuide)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const submitGuide = async () => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); return; }
    setSubmitting(true);
    setActionMsg('');
    try {
      const res = await fetch(`/api/v1/billing/guides/${id}/submit/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setGuide(data);
      setActionMsg('Guia enviada com sucesso!');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-gray-100 rounded animate-pulse" />
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-5 bg-gray-100 rounded animate-pulse w-3/4" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !guide) {
    return (
      <div className="space-y-4">
        <button onClick={() => router.back()} className="text-sm text-gray-500 hover:text-gray-700">← Voltar</button>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      </div>
    );
  }

  const canSubmit = guide && (guide.status === 'draft' || guide.status === 'pending');
  const isDenied = guide?.status === 'denied';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => router.back()} className="text-gray-400 hover:text-gray-600 text-sm">← Voltar</button>
        <h1 className="text-2xl font-semibold text-gray-900">
          Guia #{guide?.guide_number ?? guide?.id}
        </h1>
        {guide?.status && (
          <span className={`inline-flex px-3 py-1 rounded-full text-sm font-medium ${STATUS_BADGE[guide.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {STATUS_LABEL[guide.status] ?? guide.status}
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}
      {actionMsg && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">{actionMsg}</div>
      )}

      {/* Guide details card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Dados da Guia</h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
          <Field label="Nº da Guia" value={guide?.guide_number} />
          <Field label="Paciente" value={guide?.patient_name ?? guide?.patient} />
          <Field label="Operadora" value={guide?.provider_name ?? guide?.provider} />
          <Field label="Tipo de Guia" value={guide?.guide_type_display ?? guide?.guide_type} />
          <Field label="Competência" value={guide?.competency} />
          <Field label="Nº Carteirinha" value={guide?.insured_card_number} />
          <Field label="Valor Total" value={fmtCurrency(guide?.total_value)} />
          <Field label="Criado em" value={guide?.created_at ? new Date(guide.created_at).toLocaleString('pt-BR') : null} />
          <Field label="Encontro" value={guide?.encounter} />
        </dl>
      </div>

      {/* Items table */}
      {guide?.items && guide.items.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900">Procedimentos</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {['#', 'Descrição', 'Qtd', 'Valor Unit.', 'Total'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {guide.items.map((item: any, idx: number) => (
                <tr key={item.id ?? idx}>
                  <td className="px-4 py-3 text-gray-500">{idx + 1}</td>
                  <td className="px-4 py-3 text-gray-900">{item.description ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-700">{item.quantity}</td>
                  <td className="px-4 py-3 text-gray-700">{fmtCurrency(item.unit_value)}</td>
                  <td className="px-4 py-3 text-gray-900 font-medium">{fmtCurrency(item.total_value ?? (item.quantity * item.unit_value))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Glosas section */}
      {isDenied && (
        <div className="bg-white rounded-xl border border-red-200 p-6">
          <h2 className="font-semibold text-red-700 mb-3">Glosas</h2>
          {guide?.glosas && guide.glosas.length > 0 ? (
            <ul className="space-y-2">
              {guide.glosas.map((g: any, i: number) => (
                <li key={g.id ?? i} className="text-sm text-gray-700 border border-gray-100 rounded-lg p-3">
                  <span className="font-medium">{g.reason ?? g.motivo ?? 'Motivo não informado'}</span>
                  {g.value && <span className="ml-2 text-red-600">{fmtCurrency(g.value)}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-400">Nenhum detalhe de glosa disponível.</p>
          )}
        </div>
      )}

      {/* Action buttons */}
      {canSubmit && (
        <div className="flex gap-3">
          <button
            onClick={submitGuide}
            disabled={submitting}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Enviando...' : 'Enviar Guia'}
          </button>
        </div>
      )}
    </div>
  );
}
