import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import GuideDetailPage from './page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
  useParams: () => ({ id: 'guide-1' }),
}));

const mockFetch = vi.fn();
global.fetch = mockFetch;

function okJson(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => data } as Response);
}

function statusJson(status: number, data: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response);
}

// Guia de SADT: o tipo mais comum da tela e o que NÃO tem tipo de faturamento.
// O `guide_type` agora é significativo — a UI de dm_tipoFaturamento depende
// dele —, então a fixture declara o código, não só o rótulo.
const draftGuide = {
  id: 'guide-1',
  guide_number: 'GUIA-001',
  status: 'draft',
  patient_name: 'Maria Souza',
  provider_name: 'SulAmérica Saúde',
  guide_type: 'sadt',
  guide_type_display: 'SADT',
  tipo_faturamento: '2',
  tipo_faturamento_display: 'Código 2 (rótulo a confirmar no manual ANS)',
  competency: '2026-08',
  insured_card_number: '123456',
  total_value: '150.00',
  authorization_number: '',
  authorization_date: null,
  items: [],
};

const submittedGuide = { ...draftGuide, status: 'submitted', authorization_number: 'AUTH-9', authorization_date: '2026-08-01' };

// Resumo de internação: o ÚNICO tipo de guia que emite dm_tipoFaturamento no
// XML e, por isso, o único em que o campo aparece na tela.
const internacaoDraftGuide = {
  ...draftGuide,
  guide_type: 'internacao',
  guide_type_display: 'Resumo de Internação',
};

const internacaoSubmittedGuide = { ...internacaoDraftGuide, ...submittedGuide, guide_type: 'internacao', guide_type_display: 'Resumo de Internação' };

// A lista de códigos dm_tipoFaturamento tem UMA fonte: o endpoint de choices.
// O serializer da guia não a devolve mais (não havia como servir a tela de guia
// nova a partir dele), então o mock precisa ser explícito — antes o teste
// passava pelo fallback do payload da guia e o caminho real ficava sem cobertura.
const TIPO_FATURAMENTO_OPTIONS_URL = '/api/v1/billing/guides/tipo-faturamento-options/';
const ATENDIMENTO_OPTIONS_URL = '/api/v1/billing/guides/sadt-atendimento-options/';
const atendimentoOptions = {
  tipo_atendimento: [{ value: '04', label: 'Código 04 (rótulo a confirmar no manual ANS)' }],
  regime_atendimento: [{ value: '01', label: 'Código 01 (rótulo a confirmar no manual ANS)' }],
};
const tipoFaturamentoOptions = [
  { value: '1', label: 'Código 1 (rótulo a confirmar no manual ANS)' },
  { value: '2', label: 'Código 2 (rótulo a confirmar no manual ANS)' },
];

// O combobox remoto é mockado por um botão: o alvo destes testes é o painel de
// solicitante, não a busca remota (que tem cobertura própria).
vi.mock('@/components/shared/RemoteCombobox', () => ({
  default: ({ value, onChange, label }: any) => (
    <button
      type="button"
      aria-label={label}
      onClick={() => onChange({ id: 'prof-9', user_name: 'Dra. Solicitante', council_number: '654321' })}
    >
      {value ? value.user_name : 'Buscar profissional mock'}
    </button>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('GuideDetailPage — authorization_date', () => {
  it('shows the authorization number and date fields for a draft guide', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(draftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    expect(screen.getByLabelText('Data da autorização')).not.toBeDisabled();
    expect(screen.getByLabelText('Senha de autorização')).not.toBeDisabled();
  });

  it('sends the picked date as plain YYYY-MM-DD, with no timezone shift', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method === 'PATCH') {
        return okJson({ ...draftGuide, authorization_number: 'AUTH-1', authorization_date: '2026-08-31' });
      }
      if (url.endsWith('/api/v1/billing/guides/guide-1/')) {
        return okJson(draftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText('Senha de autorização'), 'AUTH-1');
    // Last day of the month — a classic UTC-conversion off-by-one trap.
    await user.type(screen.getByLabelText('Data da autorização'), '2026-08-31');
    await user.click(screen.getByRole('button', { name: 'Salvar autorização' }));

    await waitFor(() => {
      expect(screen.getByText('Autorização salva.')).toBeInTheDocument();
    });

    const patchCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).endsWith('/api/v1/billing/guides/guide-1/') && (init as RequestInit | undefined)?.method === 'PATCH'
    ));
    expect(patchCall).toBeTruthy();
    expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual({
      authorization_number: 'AUTH-1',
      authorization_date: '2026-08-31',
    });
  });

  it('saves with a null date when the field is left empty — the field is optional', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method === 'PATCH') {
        return okJson({ ...draftGuide, authorization_number: 'AUTH-2', authorization_date: null });
      }
      if (url.endsWith('/api/v1/billing/guides/guide-1/')) {
        return okJson(draftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText('Senha de autorização'), 'AUTH-2');
    await user.click(screen.getByRole('button', { name: 'Salvar autorização' }));

    await waitFor(() => {
      expect(screen.getByText('Autorização salva.')).toBeInTheDocument();
    });

    const patchCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).endsWith('/api/v1/billing/guides/guide-1/') && (init as RequestInit | undefined)?.method === 'PATCH'
    ));
    expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual({
      authorization_number: 'AUTH-2',
      authorization_date: null,
    });
  });

  it('disables both fields and explains why once the guide leaves draft', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(submittedGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    expect(screen.getByLabelText('Senha de autorização')).toBeDisabled();
    expect(screen.getByLabelText('Data da autorização')).toBeDisabled();
    expect(screen.getByText(/não pode mais ser editada/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Salvar autorização' })).not.toBeInTheDocument();
  });

  it('surfaces the backend guard message on a rejected PATCH (400)', async () => {
    // Simulates the race where the guide leaves draft between load and save.
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method === 'PATCH') {
        return statusJson(400, {
          detail: "Guia 'GUIA-001' está com status 'pending' e não pode mais ser editada.",
        });
      }
      if (url.endsWith('/api/v1/billing/guides/guide-1/')) {
        return okJson(draftGuide);
      }
      return okJson({});
    });

    const user = userEvent.setup();
    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText('Senha de autorização'), 'AUTH-3');
    await user.click(screen.getByRole('button', { name: 'Salvar autorização' }));

    await waitFor(() => {
      expect(screen.getByText(/não pode mais ser editada/)).toBeInTheDocument();
    });
  });
});

describe('GuideDetailPage — atendimento (SP/SADT)', () => {
  const sadtCompleta = {
    ...draftGuide,
    tipo_atendimento: '04',
    tipo_atendimento_display: 'Código 04 (rótulo a confirmar no manual ANS)',
    regime_atendimento: '01',
    regime_atendimento_display: 'Código 01 (rótulo a confirmar no manual ANS)',
  };

  it('fills both selects from the choices endpoint', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson(atendimentoOptions);
      return okJson(sadtCompleta);
    });

    render(<GuideDetailPage />);

    await waitFor(() =>
      expect(screen.getByLabelText('Tipo de atendimento (TISS)')).toHaveValue('04'),
    );
    expect(screen.getByLabelText('Regime de atendimento (TISS)')).toHaveValue('01');
  });

  it('survives a malformed options response instead of blanking the page', async () => {
    // Uma resposta fora do contrato (proxy, 302 para HTML) deixaria os arrays
    // undefined e o .map do select derrubaria a PÁGINA INTEIRA. Select vazio é
    // ruim; tela em branco é pior — e foi o que aconteceu antes da normalização.
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson({ inesperado: true });
      return okJson(sadtCompleta);
    });

    render(<GuideDetailPage />);

    await waitFor(() => expect(screen.getByText('Atendimento (TISS)')).toBeInTheDocument());
    expect(screen.getByLabelText('Tipo de atendimento (TISS)')).toBeInTheDocument();
  });

  it('saves both fields in one PATCH', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push([url, init]);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson(atendimentoOptions);
      if (init?.method === 'PATCH') return okJson(sadtCompleta);
      return okJson(draftGuide);
    });

    render(<GuideDetailPage />);
    await waitFor(() => expect(screen.getByText('Atendimento (TISS)')).toBeInTheDocument());

    await userEvent.selectOptions(screen.getByLabelText('Tipo de atendimento (TISS)'), '04');
    await userEvent.selectOptions(screen.getByLabelText('Regime de atendimento (TISS)'), '01');
    await userEvent.click(screen.getByRole('button', { name: 'Salvar atendimento' }));

    await waitFor(() =>
      expect(screen.getByText('Dados de atendimento salvos.')).toBeInTheDocument(),
    );
    const patch = calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({
      tipo_atendimento: '04',
      regime_atendimento: '01',
    });
  });

  it('blocks the save until BOTH fields are chosen', async () => {
    // ctm_sp-sadtAtendimento exige os dois; salvar só um deixaria a guia
    // igualmente incapaz de gerar XML, com a falsa sensação de resolvido.
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson(atendimentoOptions);
      return okJson(draftGuide);
    });

    render(<GuideDetailPage />);
    await waitFor(() => expect(screen.getByText('Atendimento (TISS)')).toBeInTheDocument());

    expect(screen.getByRole('button', { name: 'Salvar atendimento' })).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText('Tipo de atendimento (TISS)'), '04');
    expect(screen.getByRole('button', { name: 'Salvar atendimento' })).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText('Regime de atendimento (TISS)'), '01');
    expect(screen.getByRole('button', { name: 'Salvar atendimento' })).not.toBeDisabled();
  });

  it('hides the panel for a guide type without dadosAtendimento', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson(atendimentoOptions);
      return okJson(internacaoDraftGuide);
    });

    render(<GuideDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Tipo de faturamento (TISS)' }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('Atendimento (TISS)')).not.toBeInTheDocument();
  });

  it('locks both selects once the guide leaves draft', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith(ATENDIMENTO_OPTIONS_URL)) return okJson(atendimentoOptions);
      return okJson({ ...sadtCompleta, status: 'submitted' });
    });

    render(<GuideDetailPage />);
    await waitFor(() => expect(screen.getByText('Atendimento (TISS)')).toBeInTheDocument());

    expect(screen.getByLabelText('Tipo de atendimento (TISS)')).toBeDisabled();
    expect(screen.getByLabelText('Regime de atendimento (TISS)')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Salvar atendimento' })).not.toBeInTheDocument();
  });
});

describe('GuideDetailPage — profissional solicitante (SP/SADT)', () => {
  const sadtComSolicitante = {
    ...draftGuide,
    requesting_professional: 'prof-9',
    requesting_professional_name: 'Dra. Solicitante',
  };

  it('shows the panel for a SADT guide, where dadosSolicitante exists', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      return okJson(sadtComSolicitante);
    });

    render(<GuideDetailPage />);

    await waitFor(() =>
      expect(screen.getByText('Profissional solicitante (TISS)')).toBeInTheDocument(),
    );
    expect(screen.getByText('Dra. Solicitante')).toBeInTheDocument();
  });

  it('hides the panel for a guide type that has no dadosSolicitante', async () => {
    // Resumo de internação NÃO tem o bloco (tem numeroGuiaSolicitacaoInternacao,
    // que é outra coisa). Mostrar o painel ali convidaria a preencher um campo
    // que nunca vira XML — o mesmo defeito já corrigido no tipo de faturamento.
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      return okJson(internacaoDraftGuide);
    });

    render(<GuideDetailPage />);

    // getByRole('heading'): 'Tipo de faturamento (TISS)' aparece também como
    // rótulo no <dl> de resumo, e um getByText solto acha os dois.
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Tipo de faturamento (TISS)' }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('Profissional solicitante (TISS)')).not.toBeInTheDocument();
  });

  it('saves the picked professional with a PATCH', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push([url, init]);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (init?.method === 'PATCH') return okJson(sadtComSolicitante);
      return okJson(draftGuide);
    });

    render(<GuideDetailPage />);
    await waitFor(() =>
      expect(screen.getByText('Profissional solicitante (TISS)')).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Profissional solicitante' }));
    await userEvent.click(screen.getByRole('button', { name: 'Salvar solicitante' }));

    await waitFor(() =>
      expect(screen.getByText('Profissional solicitante salvo.')).toBeInTheDocument(),
    );
    const patch = calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({
      requesting_professional: 'prof-9',
    });
  });

  it('locks the solicitante once the guide leaves draft', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      return okJson({ ...sadtComSolicitante, status: 'submitted' });
    });

    render(<GuideDetailPage />);

    await waitFor(() =>
      expect(screen.getByText('Profissional solicitante (TISS)')).toBeInTheDocument(),
    );
    expect(screen.queryByRole('button', { name: 'Salvar solicitante' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Profissional solicitante' })).not.toBeInTheDocument();
  });
});

describe('GuideDetailPage — tipo de faturamento (TISS)', () => {
  it('shows the panel and the summary row for an internação guide', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(internacaoDraftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Tipo de faturamento (TISS)' })).toBeInTheDocument();
    });

    // A linha do resumo mostra o código gravado na guia.
    const summaryTerm = screen.getAllByText('Tipo de faturamento (TISS)').find((el) => el.tagName === 'DT');
    expect(summaryTerm).toBeDefined();
    expect(summaryTerm!.parentElement).toHaveTextContent('Código 2 (rótulo a confirmar no manual ANS)');
    expect(screen.getByLabelText('Tipo de faturamento (TISS)')).toHaveValue('2');
  });

  it('hides panel, summary row and the choices request for a guide that never emits the field', async () => {
    // dm_tipoFaturamento sai só no XML de resumo de internação. Numa guia de
    // SADT o campo aparecia mesmo assim, convidando o faturista a declarar um
    // código ANS que nenhum documento carregaria.
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(draftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Senha de autorização')).toBeInTheDocument();
    });

    // Um único queryByText cobre o título do painel, o rótulo do select e o
    // <dt> do resumo — nenhum dos três pertence a esta guia.
    expect(screen.queryByText('Tipo de faturamento (TISS)')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Salvar tipo de faturamento' })).not.toBeInTheDocument();
    expect(mockFetch.mock.calls.some(([url]) => String(url).endsWith(TIPO_FATURAMENTO_OPTIONS_URL))).toBe(false);
  });

  it('fills the select from the choices endpoint, not from the guide payload', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(internacaoDraftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Tipo de faturamento (TISS)')).toHaveValue('2');
    });
    // Os quatro códigos ANS vêm do endpoint; a guia devolve só o valor gravado.
    expect(screen.getByRole('option', { name: /Código 1/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Código 2/ })).toBeInTheDocument();
    expect(mockFetch.mock.calls.some(([url]) => String(url).endsWith(TIPO_FATURAMENTO_OPTIONS_URL))).toBe(true);
  });

  it('warns in place when the choices endpoint fails instead of leaving an empty select', async () => {
    // 401/500 no endpoint deixava o select vazio e silencioso — indistinguível
    // de "esta guia não tem tipo de faturamento".
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return statusJson(401, { detail: 'unauth' });
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(internacaoDraftGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByText(/Não foi possível carregar os códigos de tipo de faturamento/)).toBeInTheDocument();
    });
    expect(screen.queryByRole('option', { name: /Código 1/ })).not.toBeInTheDocument();
  });

  it('saves the picked code with a PATCH and confirms in its own panel', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method === 'PATCH') {
        return okJson({ ...internacaoDraftGuide, tipo_faturamento: '1' });
      }
      if (url.endsWith('/api/v1/billing/guides/guide-1/')) return okJson(internacaoDraftGuide);
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Código 1/ })).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText('Tipo de faturamento (TISS)'), '1');
    await user.click(screen.getByRole('button', { name: 'Salvar tipo de faturamento' }));

    await waitFor(() => {
      expect(screen.getByText('Tipo de faturamento salvo.')).toBeInTheDocument();
    });
    const patchCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).endsWith('/api/v1/billing/guides/guide-1/') && (init as RequestInit | undefined)?.method === 'PATCH'
    ));
    expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual({ tipo_faturamento: '1' });
  });

  it('shows a failed save inside the tipo de faturamento panel, never in the authorization panel', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method === 'PATCH') {
        return statusJson(400, {
          detail: "Guia 'GUIA-001' está com status 'pending' e não pode mais ser editada.",
        });
      }
      if (url.endsWith('/api/v1/billing/guides/guide-1/')) return okJson(internacaoDraftGuide);
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Salvar tipo de faturamento' })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Salvar tipo de faturamento' }));

    const message = await screen.findByText(/não pode mais ser editada\./);
    // O erro tem que estar no painel de quem clicou. Antes ele era escrito em
    // authError e saía dentro de "Autorização TISS", num painel diferente.
    const tipoPanel = screen.getByRole('heading', { name: 'Tipo de faturamento (TISS)' }).closest('div');
    const authPanel = screen.getByRole('heading', { name: 'Autorização TISS' }).closest('div');
    expect(tipoPanel).toContainElement(message);
    expect(authPanel).not.toContainElement(message);
  });

  it('disables the select once the guide leaves draft — the backend locks it there', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(TIPO_FATURAMENTO_OPTIONS_URL)) return okJson(tipoFaturamentoOptions);
      if (url.endsWith('/api/v1/billing/guides/guide-1/') && init?.method !== 'PATCH') {
        return okJson(internacaoSubmittedGuide);
      }
      return okJson({});
    });

    render(<GuideDetailPage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Tipo de faturamento (TISS)')).toBeInTheDocument();
    });

    expect(screen.getByLabelText('Tipo de faturamento (TISS)')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Salvar tipo de faturamento' })).not.toBeInTheDocument();
    expect(screen.getByText(/o tipo de faturamento só muda enquanto a guia é rascunho/)).toBeInTheDocument();
  });
});
