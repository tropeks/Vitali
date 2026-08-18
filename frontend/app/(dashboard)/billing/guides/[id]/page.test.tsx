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

const draftGuide = {
  id: 'guide-1',
  guide_number: 'GUIA-001',
  status: 'draft',
  patient_name: 'Maria Souza',
  provider_name: 'SulAmérica Saúde',
  guide_type_display: 'SADT',
  tipo_faturamento: '2',
  tipo_faturamento_display: 'Código 2 (rótulo a confirmar no manual ANS)',
  tipo_faturamento_options: [{ value: '2', label: 'Código 2 (rótulo a confirmar no manual ANS)' }],
  competency: '2026-08',
  insured_card_number: '123456',
  total_value: '150.00',
  authorization_number: '',
  authorization_date: null,
  items: [],
};

const submittedGuide = { ...draftGuide, status: 'submitted', authorization_number: 'AUTH-9', authorization_date: '2026-08-01' };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('GuideDetailPage — authorization_date', () => {
  it('shows the authorization number and date fields for a draft guide', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
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
    expect(screen.getByLabelText('Tipo de faturamento (TISS)')).toHaveValue('2');
  });

  it('sends the picked date as plain YYYY-MM-DD, with no timezone shift', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
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
