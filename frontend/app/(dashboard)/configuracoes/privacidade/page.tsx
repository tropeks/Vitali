'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'

interface PrivacySettings {
  dpo_name: string;
  dpo_email: string;
  dpa_signed: boolean;
}

export default function PrivacidadePage() {
  const [settings, setSettings] = useState<PrivacySettings>({
    dpo_name: '',
    dpo_email: '',
    dpa_signed: false
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<PrivacySettings>('/api/v1/tenant/privacy-settings/');
      setSettings(data);
    } catch {
      // Falback to empty if not found
      setSettings({ dpo_name: '', dpo_email: '', dpa_signed: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await apiFetch('/api/v1/tenant/privacy-settings/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      setSuccess(true);
    } catch {
      setError('Erro ao salvar as configurações.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Privacidade (LGPD)</h1>
        <p className="text-sm text-slate-500 mt-0.5">Gestão de DPO e Documentos de Proteção de Dados.</p>
      </div>

      {error && (
        <SectionState
          title="Erro de carregamento"
          detail={error}
          tone="critical"
        />
      )}

      {success && (
        <div className="p-4 bg-green-50 text-green-700 rounded-md text-sm mb-4">
          Configurações salvas com sucesso.
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Carregando...</p>
      ) : (
        <div className="bg-white p-6 rounded-lg border border-slate-200 max-w-2xl flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Nome do Encarregado (DPO)</label>
            <input
              type="text"
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
              value={settings.dpo_name}
              onChange={e => setSettings({ ...settings, dpo_name: e.target.value })}
              placeholder="Ex: João da Silva"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Email do DPO</label>
            <input
              type="email"
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
              value={settings.dpo_email}
              onChange={e => setSettings({ ...settings, dpo_email: e.target.value })}
              placeholder="Ex: dpo@clinica.com"
            />
          </div>

          <div className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              id="dpa_signed"
              className="h-4 w-4 text-blue-600 rounded border-slate-300"
              checked={settings.dpa_signed}
              onChange={e => setSettings({ ...settings, dpa_signed: e.target.checked })}
            />
            <label htmlFor="dpa_signed" className="text-sm font-medium text-slate-700">
              Data Processing Agreement (DPA) Assinado
            </label>
          </div>

          <div className="mt-4 flex gap-2">
            <button
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
