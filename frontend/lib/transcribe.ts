/**
 * How the audio recorder explains a failed POST /scribe/transcribe/.
 *
 * Ordem 024: a 403 is a compliance refusal — the clinic's signed DPA does not
 * name OpenAI, so server-side transcription is not available to it at all.
 * It is not a transient failure, so the message never says "try again" and
 * the recorder stops offering the action (`unavailable`).
 */
export interface TranscribeFailure {
  message: string;
  unavailable: boolean;
}

export function describeTranscribeFailure(
  status: number,
  data: { detail?: string; reason?: string },
): TranscribeFailure {
  if (status === 403) {
    return {
      message:
        'Transcrição por áudio indisponível para esta clínica. Use o ditado do navegador ou digite o texto.',
      unavailable: true,
    };
  }
  const detail = data.detail ?? '';
  if (status === 400 && detail.toLowerCase().includes('grande')) {
    return {
      message: 'Áudio muito grande. Grave um áudio mais curto (máx. 25 MB).',
      unavailable: false,
    };
  }
  return {
    message: detail || `Erro ao transcrever áudio (${status}).`,
    unavailable: false,
  };
}
