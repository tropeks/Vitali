'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';

interface AudioRecorderProps {
  onTranscription: (text: string) => void;
  encounterId: string;
}

const MAX_RECORDING_SECONDS = 300; // 5 minutes

export function AudioRecorder({ onTranscription, encounterId }: AudioRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  // Auto-stop at max duration
  useEffect(() => {
    if (recording && elapsed >= MAX_RECORDING_SECONDS) {
      stopRecording();
    }
  }, [elapsed, recording]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopTimer();
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, []);

  const startRecording = async () => {
    setError(null);
    chunksRef.current = [];

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError('Não foi possível acessar o microfone. Verifique as permissões do navegador.');
      return;
    }

    streamRef.current = stream;

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    const mediaRecorder = new MediaRecorder(stream, { mimeType });
    mediaRecorderRef.current = mediaRecorder;

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      const audioBlob = new Blob(chunksRef.current, { type: mimeType });
      handleTranscribe(audioBlob, mimeType);
    };

    mediaRecorder.start();
    setRecording(true);
    setElapsed(0);

    timerRef.current = setInterval(() => {
      setElapsed(prev => prev + 1);
    }, 1000);
  };

  const stopRecording = useCallback(() => {
    stopTimer();
    setRecording(false);
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const handleTranscribe = async (blob: Blob, mimeType: string) => {
    setTranscribing(true);
    setError(null);

    const formData = new FormData();
    // Use a base MIME type without codec params for the filename hint
    const ext = mimeType.startsWith('audio/webm') ? 'webm' : 'ogg';
    formData.append('audio', blob, `audio.${ext}`);

    try {
      const token = getAccessToken();
      const res = await fetch(`/api/v1/encounters/${encounterId}/scribe/transcribe/`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (res.status === 400 && (data.detail ?? '').toLowerCase().includes('grande')) {
          setError('Áudio muito grande. Grave um áudio mais curto (máx. 25 MB).');
        } else {
          setError(data.detail ?? `Erro ao transcrever áudio (${res.status}).`);
        }
        return;
      }

      const data = await res.json();
      onTranscription(data.transcription ?? '');
    } catch {
      setError('Erro de rede ao enviar áudio. Verifique sua conexão.');
    } finally {
      setTranscribing(false);
    }
  };

  const formatElapsed = (secs: number) => {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  if (transcribing) {
    return (
      <div className="flex flex-col items-center gap-3 py-4">
        <Loader2 size={24} className="animate-spin text-purple-500" />
        <p className="text-sm text-purple-700">Transcrevendo...</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <p className="text-xs text-red-600">{error}</p>
      )}

      <div className="flex items-center gap-3">
        {!recording ? (
          <button
            onClick={startRecording}
            className="inline-flex items-center gap-1.5 text-xs font-medium bg-purple-600 text-white hover:bg-purple-700 px-4 py-2 rounded-lg transition-colors"
          >
            <Mic size={13} />
            Gravar Áudio
          </button>
        ) : (
          <>
            <span className="text-xs font-mono text-purple-700 tabular-nums">
              {formatElapsed(elapsed)} / {formatElapsed(MAX_RECORDING_SECONDS)}
            </span>
            <button
              onClick={stopRecording}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-red-600 text-white hover:bg-red-700 px-4 py-2 rounded-lg transition-colors"
            >
              <MicOff size={13} />
              Parar
            </button>
          </>
        )}
      </div>

      {recording && (
        <p className="text-xs text-purple-500">
          Gravando... Clique em &ldquo;Parar&rdquo; quando terminar.
        </p>
      )}
    </div>
  );
}
