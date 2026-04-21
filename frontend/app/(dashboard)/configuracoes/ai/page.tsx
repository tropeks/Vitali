'use client';

import { useEffect, useState } from 'react';
import { CheckCircle, AlertCircle, Bot } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { DPASignModal } from '@/components/settings/DPASignModal';

interface DPAStatus {
  is_signed: boolean;
  signed_at: string | null;
  signed_by_name: string | null;
  ai_scribe_enabled: boolean;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('pt-BR');
}

export default function AISettingsPage() {
  const [status, setStatus] = useState<DPAStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const raw = document.cookie
        .split('; ')
        .find((c) => c.startsWith('vitali_user='))
        ?.split('=')[1];
      if (raw) {
        try {
          const user = JSON.parse(decodeURIComponent(raw));
          setIsAdmin(user?.role_name === 'admin');
        } catch {
          // ignore
        }
      }
    }
  }, []);

  async function fetchStatus() {
    const token = getAccessToken();
    try {
      const res = await fetch('/api/v1/settings/dpa/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data: DPAStatus = await res.json();
        setStatus(data);
      }
    } catch {
      // ignore — show empty state
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  async function handleSign() {
    setSigning(true);
    setError(null);
    const token = getAccessToken();
    try {
      const res = await fetch('/api/v1/settings/dpa/sign/', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data: DPAStatus = await res.json();
        setStatus(data);
        setShowModal(false);
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body?.error?.message ?? `Erro ${res.status}`);
      }
    } catch {
      setError('Falha ao assinar o DPA. Verifique sua conexão.');
    } finally {
      setSigning(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] text-slate-400 text-sm">
        Carregando...
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6 py-8 px-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Inteligência Artificial</h1>
        <p className="text-sm text-slate-500 mt-1">
          Gerencie o Acordo de Processamento de Dados e as configurações de IA da clínica.
        </p>
      </div>

      {/* DPA Status Card */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h2 className="text-sm font-semibold text-slate-800 uppercase tracking-wide">
            Acordo de Processamento de Dados (DPA)
          </h2>
          {status?.is_signed ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
              <CheckCircle size={13} />
              DPA assinado
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-700">
              <AlertCircle size={13} />
              DPA não assinado
            </span>
          )}
        </div>

        {status?.is_signed ? (
          <div className="space-y-1.5 text-sm text-slate-600">
            <p>
              <span className="font-medium text-slate-700">Data de assinatura:</span>{' '}
              {formatDate(status.signed_at)}
            </p>
            <p>
              <span className="font-medium text-slate-700">Assinado por:</span>{' '}
              {status.signed_by_name ?? '—'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              Para utilizar os recursos de Inteligência Artificial (incluindo IA Clínica / Scribe),
              é necessário assinar o Acordo de Processamento de Dados em conformidade com a LGPD.
            </p>
            <div>
              {isAdmin ? (
                <button
                  onClick={() => setShowModal(true)}
                  className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Assinar DPA
                </button>
              ) : (
                <div className="inline-flex items-center gap-2">
                  <button
                    disabled
                    title="Apenas administradores podem assinar o DPA"
                    className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-blue-600 rounded-lg opacity-40 cursor-not-allowed"
                  >
                    Assinar DPA
                  </button>
                  <span className="text-xs text-slate-500">
                    Apenas administradores podem assinar.
                  </span>
                </div>
              )}
            </div>
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
          </div>
        )}
      </div>

      {/* AI Scribe info — only shown after DPA is signed and scribe is enabled */}
      {status?.is_signed && status?.ai_scribe_enabled && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Bot size={18} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-slate-800 uppercase tracking-wide">
              IA Clínica (Scribe)
            </h2>
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
              Ativo
            </span>
          </div>
          <p className="text-sm text-slate-600">
            O módulo de IA Clínica está habilitado. As transcrições de consultas são processadas
            automaticamente para geração de notas SOAP, com armazenamento criptografado em conformidade
            com a LGPD.
          </p>
        </div>
      )}

      {showModal && (
        <DPASignModal
          onConfirm={handleSign}
          onClose={() => { setShowModal(false); setError(null); }}
          loading={signing}
        />
      )}
    </div>
  );
}
