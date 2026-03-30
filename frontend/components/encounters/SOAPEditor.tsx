'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';

interface SOAPNote {
  id: number;
  encounter: string;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  cid10_codes: string[];
  updated_at: string;
}

interface SOAPEditorProps {
  soapNote: SOAPNote | null;
  readOnly?: boolean;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

async function patchSoap(id: number, data: Partial<SOAPNote>): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1/soap-notes/${id}/`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`${res.status}`);
}

const FIELDS = [
  { key: 'subjective', label: 'S — Subjetivo', placeholder: 'Queixa principal, história da doença atual, sintomas relatados pelo paciente...' },
  { key: 'objective', label: 'O — Objetivo', placeholder: 'Exame físico, sinais vitais, achados laboratoriais, exames de imagem...' },
  { key: 'assessment', label: 'A — Avaliação', placeholder: 'Diagnóstico, hipóteses diagnósticas, códigos CID-10, impressão clínica...' },
  { key: 'plan', label: 'P — Plano', placeholder: 'Conduta terapêutica, prescrição, exames solicitados, data de retorno...' },
] as const;

export function SOAPEditor({ soapNote, readOnly = false }: SOAPEditorProps) {
  const [values, setValues] = useState({
    subjective: soapNote?.subjective ?? '',
    objective: soapNote?.objective ?? '',
    assessment: soapNote?.assessment ?? '',
    plan: soapNote?.plan ?? '',
  });
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<typeof values>(values);

  // Keep pending ref in sync
  useEffect(() => { pendingRef.current = values; }, [values]);

  const triggerSave = useCallback(() => {
    if (!soapNote?.id || readOnly) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setSaveStatus('saving');
    debounceRef.current = setTimeout(async () => {
      try {
        await patchSoap(soapNote.id, pendingRef.current);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } catch {
        setSaveStatus('error');
      }
    }, 800);
  }, [soapNote?.id, readOnly]);

  const handleChange = (field: keyof typeof values, value: string) => {
    setValues(v => ({ ...v, [field]: value }));
    triggerSave();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Nota SOAP</h2>
        <div className="text-xs text-gray-400">
          {saveStatus === 'saving' && <span className="text-blue-500">Salvando...</span>}
          {saveStatus === 'saved' && <span className="text-green-600">✓ Salvo</span>}
          {saveStatus === 'error' && <span className="text-red-500">Erro ao salvar</span>}
          {saveStatus === 'idle' && soapNote?.updated_at && (
            <span>Salvo {new Date(soapNote.updated_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
          )}
        </div>
      </div>

      {FIELDS.map(({ key, label, placeholder }) => (
        <div key={key} className="space-y-1">
          <label className="block text-sm font-medium text-gray-700">{label}</label>
          <textarea
            value={values[key]}
            onChange={e => handleChange(key, e.target.value)}
            readOnly={readOnly}
            placeholder={readOnly ? '' : placeholder}
            rows={4}
            className={`w-full border rounded-lg px-3 py-2 text-sm resize-y focus:ring-2 focus:ring-blue-500 outline-none transition-colors ${
              readOnly ? 'bg-gray-50 text-gray-600 cursor-default' : 'bg-white'
            }`}
          />
        </div>
      ))}
    </div>
  );
}
