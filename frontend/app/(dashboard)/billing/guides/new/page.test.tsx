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

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
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
      items: [
        {
          tuss_code: 101,
          description: 'Consulta em pronto atendimento',
          quantity: 1,
          unit_value: '120.5',
        },
      ],
    });
  });
});
