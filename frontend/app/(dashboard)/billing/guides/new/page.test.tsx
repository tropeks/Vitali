import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NewGuidePage from './page';

const push = vi.fn();
const back = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, back }),
  useSearchParams: () => ({
    get: (key: string) => (key === 'encounter' ? 'enc-1' : null),
  }),
}));

vi.mock('@/components/billing/TUSSCodeSearch', () => ({
  default: ({ value, onChange }: any) => (
    <button
      type="button"
      onClick={() => onChange({ id: 101, code: '10101012', description: 'Consulta em pronto atendimento' })}
    >
      {value ? `${value.code} - ${value.description}` : 'Selecionar TUSS mock'}
    </button>
  ),
}));

vi.mock('@/components/billing/TUSSSuggestionInline', () => ({
  default: () => null,
}));

vi.mock('@/components/billing/GlosaRiskBadge', () => ({
  default: ({ tussCode, insurerAnsCode }: any) => (
    tussCode && insurerAnsCode ? <span>Glosa: Risco Baixo</span> : null
  ),
}));

const mockFetch = vi.fn();
global.fetch = mockFetch;

function okJson(data: unknown) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/v1/patients/')) {
      return okJson({
        results: [
          {
            id: 'p-1',
            full_name: 'Maria Souza',
            medical_record_number: 'MRN-123',
          },
        ],
      });
    }
    if (url.includes('/api/v1/billing/providers/')) {
      return okJson({
        results: [
          {
            id: 'prov-1',
            name: 'SulAmérica Saúde',
            ans_code: '006246',
          },
        ],
      });
    }
    if (url.includes('/api/v1/billing/guides/sadt-atendimento-options/')) {
      return okJson({
        tipo_atendimento: [{ value: '04', label: 'Código 04 (rótulo a confirmar no manual ANS)' }],
        regime_atendimento: [{ value: '01', label: 'Código 01 (rótulo a confirmar no manual ANS)' }],
      });
    }
    if (url.includes('/api/v1/billing/guides/tipo-faturamento-options/')) {
      return okJson([{ value: '2', label: 'Código 2 (rótulo a confirmar no manual ANS)' }]);
    }
    if (url.includes('/api/v1/encounters/enc-1/')) {
      return okJson({
        id: 'enc-1',
        patient: 'p-1',
        patient_name: 'Maria Souza',
        patient_mrn: 'MRN-123',
        status_display: 'Atendimento em aberto',
      });
    }
    if (url.includes('/api/v1/billing/guides/') && init?.method === 'POST') {
      return okJson({ id: 'guide-1' });
    }
    return Promise.resolve({
      ok: false,
      json: async () => ({ detail: 'not found' }),
    } as Response);
  });
});

describe('NewGuidePage', () => {
  it('renders the TISS workbench with encounter and patient context', async () => {
    render(<NewGuidePage />);

    expect(screen.getByText('Bancada TISS')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getAllByText('Maria Souza').length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText('MRN-123').length).toBeGreaterThan(0);
    expect(screen.getByText('Atendimento em aberto')).toBeInTheDocument();
    expect(screen.getByText('3 pendência(s)')).toBeInTheDocument();
  });

  it('blocks creation with explicit readiness blockers', async () => {
    const user = userEvent.setup();
    render(<NewGuidePage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Operadora *')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Criar guia TISS' }));

    expect(await screen.findByText(/Pendências antes de criar a guia/)).toHaveTextContent(
      'Selecionar operadora',
    );
    expect(push).not.toHaveBeenCalled();
  });

  it('creates the guide from selected context, TUSS row, and total', async () => {
    const user = userEvent.setup();
    render(<NewGuidePage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Operadora *')).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByLabelText('Operadora *'), 'prov-1');
    // guide_type default é 'sadt', então dadosAtendimento se aplica: sem tipo e
    // regime a guia nasceria incapaz de gerar XML.
    await user.selectOptions(screen.getByLabelText('Tipo de atendimento (TISS) *'), '04');
    await user.selectOptions(screen.getByLabelText('Regime de atendimento (TISS) *'), '01');
    await user.click(screen.getByRole('button', { name: 'Selecionar TUSS mock' }));
    await user.type(screen.getByLabelText('Valor unitário'), '120.5');

    expect(screen.getByText('Pronta para criar')).toBeInTheDocument();
    expect(screen.getAllByText('R$ 120,50').length).toBeGreaterThan(0);
    expect(screen.getByText('Glosa: Risco Baixo')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Criar guia TISS' }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith('/billing/guides/guide-1');
    });

    const createCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).includes('/api/v1/billing/guides/') && init?.method === 'POST'
    ));
    expect(createCall).toBeTruthy();
    expect(JSON.parse(createCall![1].body as string)).toMatchObject({
      patient: 'p-1',
      provider: 'prov-1',
      encounter: 'enc-1',
      guide_type: 'sadt',
      tipo_atendimento: '04',
      regime_atendimento: '01',
      items: [
        {
          tuss_code: 101,
          description: 'Consulta em pronto atendimento',
          quantity: 1,
          unit_value: '120.5',
        },
      ],
    });
    // SADT não emite dm_tipoFaturamento: a chave não entra no corpo. Antes o
    // POST carregava um valor que nenhum XML leria — e o `toMatchObject` acima
    // não pega chave a mais, por isso a asserção explícita.
    expect(JSON.parse(createCall![1].body as string)).not.toHaveProperty('tipo_faturamento');
  });

  it('neither shows nor fetches tipo de faturamento for the guide types this screen creates', async () => {
    // dm_tipoFaturamento sai só na guia de resumo de internação, e o seletor
    // desta tela oferece apenas SADT e consulta. O campo era, por construção,
    // UI morta: nada do que fosse escolhido ali chegaria a um XML. Enquanto o
    // seletor não oferecer "internacao", nem o campo aparece nem a lista de
    // códigos é buscada.
    const user = userEvent.setup();
    render(<NewGuidePage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Tipo de guia')).toBeInTheDocument();
    });

    expect(screen.queryByLabelText('Tipo de faturamento (TISS)')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Tipo de guia'), 'consulta');
    expect(screen.queryByLabelText('Tipo de faturamento (TISS)')).not.toBeInTheDocument();

    expect(mockFetch.mock.calls.some(
      ([url]) => String(url).includes('/api/v1/billing/guides/tipo-faturamento-options/'),
    )).toBe(false);
  });

  it('offers atendimento fields for SADT and drops them for a guide type without the block', async () => {
    // SP/SADT é criável NESTA tela, e ctm_sp-sadtAtendimento é obrigatório —
    // sem os dois campos a guia nasceria incapaz de gerar XML. Consulta não tem
    // o bloco: oferecê-lo ali convidaria a preencher o que nunca vira XML.
    const user = userEvent.setup();
    render(<NewGuidePage />);

    await waitFor(() =>
      expect(screen.getByLabelText('Tipo de atendimento (TISS) *')).toBeInTheDocument(),
    );
    expect(screen.getByLabelText('Regime de atendimento (TISS) *')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Tipo de guia'), 'consulta');

    expect(screen.queryByLabelText('Tipo de atendimento (TISS) *')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Regime de atendimento (TISS) *')).not.toBeInTheDocument();
  });

  it('lets the page-level error banner keep to the submit blockers', async () => {
    // O banner do topo é das pendências de criação e da recusa do POST. A lista
    // auxiliar de códigos não escreve nele (o aviso dela vive ao lado do campo).
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/v1/billing/providers/')) {
        return okJson({ results: [{ id: 'prov-1', name: 'SulAmérica Saúde', ans_code: '006246' }] });
      }
      return okJson({ results: [] });
    });

    render(<NewGuidePage />);

    await waitFor(() => {
      expect(screen.getByLabelText('Operadora *')).toBeInTheDocument();
    });
    expect(screen.queryByText(/Pendências antes de criar a guia/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Criar guia TISS' }));
    expect(await screen.findByText(/Pendências antes de criar a guia/)).toHaveTextContent(
      'Selecionar operadora',
    );
  });
});
