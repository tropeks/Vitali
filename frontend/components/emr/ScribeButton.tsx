'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Mic, MicOff, Loader2, CheckCircle2, AlertTriangle, X, Sparkles } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { useAIConfig } from '@/hooks/useAIConfig';
import { AudioRecorder } from './AudioRecorder';

interface SOAPFields {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
}

interface ScribeButtonProps {
  encounterId: string;
  soapNoteId: number | null;
  onApplied: () => void;
}

type ScribeState = 'idle' | 'input' | 'processing' | 'done' | 'error';

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 30; // 60s timeout

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail ?? data.error ?? `Erro ${res.status}`);
  }
  return res.json();
}

export function ScribeButton({ encounterId, soapNoteId, onApplied }: ScribeButtonProps) {
  const { scribeReady, loading: aiConfigLoading } = useAIConfig();
  const [state, setState] = useState<ScribeState>('idle');
  const [transcription, setTranscription] = useState('');
  const [soap, setSoap] = useState<SOAPFields | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [hasSpeechApi, setHasSpeechApi] = useState<boolean | null>(null);
  const pollCount = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setHasSpeechApi(!!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition));
  }, []);

  const stopPolling = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const poll = useCallback(async () => {
    pollCount.current += 1;
    try {
      const data = await apiFetch<{ status: string; soap?: SOAPFields; error?: string }>(
        `/encounters/${encounterId}/scribe/status/`
      );
      if (data.status === 'completed' && data.soap) {
        setSoap(data.soap);
        setState('done');
        return;
      }
      if (data.status === 'failed') {
        setError(data.error ?? 'Geração de nota SOAP falhou.');
        setState('error');
        return;
      }
      if (data.status === 'none') {
        // No session found — task may have been lost or not started
        setError('Sessão de transcrição não encontrada. Tente novamente.');
        setState('error');
        return;
      }
      if (pollCount.current >= MAX_POLLS) {
        setError('Tempo limite excedido. Tente novamente.');
        setState('error');
        return;
      }
      // Still processing — schedule next poll
      timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao verificar status.');
      setState('error');
    }
  }, [encounterId]);

  const startScribeWithText = async (text: string) => {
    if (!text.trim()) return;
    setState('processing');
    setError(null);
    pollCount.current = 0;
    stopPolling();
    try {
      await apiFetch(`/encounters/${encounterId}/scribe/start/`, {
        method: 'POST',
        body: JSON.stringify({ transcription: text }),
      });
      timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao iniciar transcrição.');
      setState('error');
    }
  };

  const startScribe = async () => {
    if (!transcription.trim()) return;
    await startScribeWithText(transcription);
  };

  const applyToSoap = async () => {
    if (!soap || !soapNoteId) return;
    setApplying(true);
    try {
      const token = getAccessToken();
      const res = await fetch(`/api/v1/soap-notes/${soapNoteId}/`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(soap),
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      onApplied();
      reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao aplicar nota SOAP.');
    } finally {
      setApplying(false);
    }
  };

  const reset = () => {
    stopPolling();
    setState('idle');
    setTranscription('');
    setSoap(null);
    setError(null);
    pollCount.current = 0;
  };

  // Gate the whole component: hide when the backend would refuse the request.
  // - FEATURE_AI_SCRIBE off → backend returns 404, so render nothing.
  // - DPA not signed → backend returns 403, so render nothing.
  // Doctors don't need to see a button they can't use; admins sign the DPA
  // from /configuracoes/ai. The guard runs AFTER all hooks so the hook
  // order stays stable (rules-of-hooks).
  if (aiConfigLoading || !scribeReady) {
    return null;
  }

  // ── Idle: just a button ──────────────────────────────────────────────────
  if (state === 'idle') {
    return (
      <button
        onClick={() => setState('input')}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 px-3 py-1.5 rounded-lg transition-colors"
        title="Gerar nota SOAP por transcrição com IA"
      >
        <Sparkles size={12} />
        Transcrever com IA
      </button>
    );
  }

  // ── Shared container ─────────────────────────────────────────────────────
  return (
    <div className="border border-purple-200 bg-purple-50 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-purple-600" />
          <span className="text-sm font-semibold text-purple-800">IA — Transcrição Clínica</span>
        </div>
        <button onClick={reset} className="text-purple-400 hover:text-purple-700">
          <X size={16} />
        </button>
      </div>

      {/* Input state: AudioRecorder (no Speech API) or textarea (Speech API available/loading) */}
      {state === 'input' && (
        <div className="space-y-3">
          {hasSpeechApi === false ? (
            <AudioRecorder
              encounterId={encounterId}
              onTranscription={(text) => {
                setTranscription(text);
                startScribeWithText(text);
              }}
            />
          ) : (
            <>
              <textarea
                value={transcription}
                onChange={e => setTranscription(e.target.value)}
                rows={5}
                placeholder="Cole ou escreva a transcrição da consulta aqui. A IA irá gerar a nota SOAP automaticamente..."
                className="w-full border border-purple-200 rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-purple-500 bg-white"
                autoFocus
              />
              <div className="flex gap-2 justify-end">
                <button
                  onClick={reset}
                  className="text-xs text-purple-600 hover:text-purple-800 px-3 py-1.5"
                >
                  Cancelar
                </button>
                <button
                  onClick={startScribe}
                  disabled={!transcription.trim()}
                  className="inline-flex items-center gap-1.5 text-xs font-medium bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 px-4 py-1.5 rounded-lg transition-colors"
                >
                  <Mic size={12} />
                  Gerar nota SOAP
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Processing state */}
      {state === 'processing' && (
        <div className="flex flex-col items-center gap-3 py-4">
          <Loader2 size={24} className="animate-spin text-purple-500" />
          <p className="text-sm text-purple-700 text-center">
            Gerando nota SOAP com IA...
            <br />
            <span className="text-xs text-purple-400">Isso pode levar até 60 segundos</span>
          </p>
        </div>
      )}

      {/* Done state: show SOAP fields + apply button */}
      {state === 'done' && soap && (
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 text-sm font-medium text-green-700">
            <CheckCircle2 size={14} />
            Nota SOAP gerada com sucesso
          </div>

          <div className="space-y-2 bg-white rounded-lg border border-purple-200 p-3">
            {[
              { key: 'subjective', label: 'S — Subjetivo' },
              { key: 'objective', label: 'O — Objetivo' },
              { key: 'assessment', label: 'A — Avaliação' },
              { key: 'plan', label: 'P — Plano' },
            ].map(({ key, label }) => (
              <div key={key} className="space-y-0.5">
                <p className="text-xs font-medium text-slate-500">{label}</p>
                <p className="text-xs text-slate-700 leading-relaxed">
                  {soap[key as keyof SOAPFields] || <span className="italic text-slate-400">—</span>}
                </p>
              </div>
            ))}
          </div>

          {error && (
            <p className="text-xs text-red-600">{error}</p>
          )}

          <div className="flex gap-2 justify-end">
            <button
              onClick={reset}
              className="text-xs text-purple-600 hover:text-purple-800 px-3 py-1.5"
            >
              Descartar
            </button>
            <button
              onClick={applyToSoap}
              disabled={applying || !soapNoteId}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 px-4 py-1.5 rounded-lg transition-colors"
              title={!soapNoteId ? 'Salve a consulta primeiro para aplicar a nota' : undefined}
            >
              {applying ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
              Aplicar ao prontuário
            </button>
          </div>
        </div>
      )}

      {/* Error state */}
      {state === 'error' && (
        <div className="space-y-3">
          <div className="flex items-center gap-1.5 text-sm text-red-700">
            <AlertTriangle size={14} />
            {error ?? 'Erro desconhecido'}
          </div>
          <div className="flex gap-2 justify-end">
            <button
              onClick={reset}
              className="text-xs text-slate-500 hover:text-slate-700 px-3 py-1.5"
            >
              Fechar
            </button>
            <button
              onClick={() => setState('input')}
              className="text-xs font-medium text-purple-600 hover:text-purple-800 px-3 py-1.5"
            >
              Tentar novamente
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
