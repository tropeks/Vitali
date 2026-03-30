'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

const STATUS_BADGE: Record<string, string> = {
  open: 'bg-blue-100 text-blue-700',
  closed: 'bg-yellow-100 text-yellow-700',
  submitted: 'bg-purple-100 text-purple-700',
  paid: 'bg-green-100 text-green-700',
  partial: 'bg-orange-100 text-orange-700',
};

const STATUS_LABEL: Record<string, string> = {
  open: 'Aberto',
  closed: 'Fechado',
  submitted: 'Enviado',
  paid: 'Pago',
  partial: 'Parcial',
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

export default function BatchDetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;

  const [batch, setBatch] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    fetch(`/api/v1/billing/batches/${id}/`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then(setBatch)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const closeBatch = async () => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); return; }
    setBusy(true); setError(''); setActionMsg('');
    try {
      const res = await fetch(`/api/v1/billing/batches/${id}/close/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setBatch(data);
      setActionMsg('Lote fechado com sucesso!');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const exportXml = async () => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); return; }
    setBusy(true); setError(''); setActionMsg('');
    try {
      const res = await fetch(`/api/v1/billing/batches/${id}/export/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      const url = data.url ?? data.download_url ?? data.file_url ?? '';
      setDownloadUrl(url);
      setActionMsg('XML gerado com sucesso!');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const uploadRetorno = async (file: File) => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); return; }
    setBusy(true); setError(''); setActionMsg('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/v1/billing/batches/${id}/upload_retorno/`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setBatch((prev: any) => ({ ...prev, ...data }));
      setActionMsg('Arquivo de retorno processado com sucesso!');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-gray-100 rounded animate-pulse" />
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-5 bg-gray-100 rounded animate-pulse w-3/4" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !batch) {
    return (
      <div className="space-y-4">
        <button onClick={() => router.back()} className="text-sm text-gray-500 hover:text-gray-700">← Voltar</button>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      </div>
    );
  }

  const isOpen = batch?.status === 'open';
  const isClosed = batch?.status === 'closed';
  const isClosedOrSubmitted = batch?.status === 'closed' || batch?.status === 'submitted';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => router.back()} className="text-gray-400 hover:text-gray-600 text-sm">← Voltar</button>
        <h1 className="text-2xl font-semibold text-gray-900">
          Lote {batch?.batch_number ?? batch?.id}
        </h1>
        {batch?.status && (
          <span className={`inline-flex px-3 py-1 rounded-full text-sm font-medium ${STATUS_BADGE[batch.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {STATUS_LABEL[batch.status] ?? batch.status}
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}
      {actionMsg && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">
          {actionMsg}
          {downloadUrl && (
            <a
              href={downloadUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-2 underline font-medium"
            >
              Baixar XML
            </a>
          )}
        </div>
      )}

      {/* Batch info */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Dados do Lote</h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
          <Field label="Nº do Lote" value={batch?.batch_number} />
          <Field label="Operadora" value={batch?.provider_name ?? batch?.provider} />
          <Field label="Qtd Guias" value={batch?.guide_count} />
          <Field label="Valor Total" value={fmtCurrency(batch?.total_value)} />
          <Field label="Criado em" value={batch?.created_at ? new Date(batch.created_at).toLocaleDateString('pt-BR') : null} />
          <Field label="Fechado em" value={batch?.closed_at ? new Date(batch.closed_at).toLocaleDateString('pt-BR') : null} />
        </dl>
      </div>

      {/* Guides in batch */}
      {batch?.guides && batch.guides.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900">Guias no Lote</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {['Nº Guia', 'Paciente', 'Valor', 'Status'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {batch.guides.map((g: any) => (
                <tr
                  key={g.id}
                  className="hover:bg-blue-50 cursor-pointer transition-colors"
                  onClick={() => router.push(`/billing/guides/${g.id}`)}
                >
                  <td className="px-4 py-3 font-mono text-gray-700">{g.guide_number ?? g.id}</td>
                  <td className="px-4 py-3 text-gray-900">{g.patient_name ?? g.patient ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-700">{fmtCurrency(g.total_value)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[g.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {STATUS_LABEL[g.status] ?? g.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        {isOpen && (
          <button
            onClick={closeBatch}
            disabled={busy}
            className="bg-yellow-500 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-yellow-600 disabled:opacity-50"
          >
            {busy ? 'Fechando...' : 'Fechar Lote'}
          </button>
        )}
        {isClosed && (
          <button
            onClick={exportXml}
            disabled={busy}
            className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? 'Gerando...' : 'Exportar XML'}
          </button>
        )}
        {isClosedOrSubmitted && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xml,.txt"
              className="hidden"
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) uploadRetorno(file);
                e.target.value = '';
              }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
              className="bg-gray-700 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
            >
              {busy ? 'Enviando...' : 'Upload Retorno'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
