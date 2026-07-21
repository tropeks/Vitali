'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState, Button } from '@/components/shared'

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
        <h1 className="text-2xl font-semibold text-neu-ink">Privacidade (LGPD)</h1>
        <p className="text-sm text-neu-inkSoft mt-0.5">Gestão de DPO e Documentos de Proteção de Dados.</p>
      </div>

      {error && (
        <SectionState
          title="Erro de carregamento"
          detail={error}
          tone="critical"
        />
      )}

      {success && (
        <div className="p-4 bg-neu-success/10 text-neu-success border border-neu-success/20 rounded-md text-sm mb-4">
          Configurações salvas com sucesso.
        </div>
      )}

      {loading ? (
        <p className="text-sm text-neu-inkMuted">Carregando...</p>
      ) : (
        <div className="bg-neu-panel p-6 rounded-xl shadow-neu-panel border border-white max-w-2xl flex flex-col gap-4">
          <div>
            <label className="neu-label">Nome do Encarregado (DPO)</label>
            <input
              type="text"
              className="neu-input"
              value={settings.dpo_name}
              onChange={e => setSettings({ ...settings, dpo_name: e.target.value })}
              placeholder="Ex: João da Silva"
            />
          </div>

          <div>
            <label className="neu-label">Email do DPO</label>
            <input
              type="email"
              className="neu-input"
              value={settings.dpo_email}
              onChange={e => setSettings({ ...settings, dpo_email: e.target.value })}
              placeholder="Ex: dpo@clinica.com"
            />
          </div>

          <div className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              id="dpa_signed"
              className="h-4 w-4 text-neu-brand rounded border-neu-inkMuted/40"
              checked={settings.dpa_signed}
              onChange={e => setSettings({ ...settings, dpa_signed: e.target.checked })}
            />
            <label htmlFor="dpa_signed" className="text-sm font-medium text-neu-ink">
              Data Processing Agreement (DPA) Assinado
            </label>
          </div>

          <div className="mt-4 flex gap-2">
            <Button variant="primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar'}
            </Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
