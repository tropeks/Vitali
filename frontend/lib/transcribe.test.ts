import { describe, expect, it } from 'vitest';

import { describeTranscribeFailure } from './transcribe';

// Ordem 024: a 403 on /scribe/transcribe/ is a compliance refusal (the clinic's
// DPA does not name OpenAI), not a transient failure. The recorder must say
// so and stop offering the action — no "try again".
describe('describeTranscribeFailure', () => {
  it('403 marks audio transcription as unavailable for this clinic', () => {
    const r = describeTranscribeFailure(403, { reason: 'provider_not_in_dpa' });
    expect(r.unavailable).toBe(true);
    expect(r.message).toMatch(/indisponível para esta clínica/);
    expect(r.message).not.toMatch(/tente novamente/i);
  });

  it('503 stays a transient error the user may retry', () => {
    const r = describeTranscribeFailure(503, { detail: 'Serviço de transcrição indisponível.' });
    expect(r.unavailable).toBe(false);
    expect(r.message).toBe('Serviço de transcrição indisponível.');
  });

  it('keeps the file-too-large message', () => {
    const r = describeTranscribeFailure(400, { detail: 'Arquivo de áudio muito grande.' });
    expect(r.unavailable).toBe(false);
    expect(r.message).toMatch(/25 MB/);
  });
});
