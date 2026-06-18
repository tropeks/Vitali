import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PrivacidadePage from './page';

const mockApiFetch = vi.fn();
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PrivacidadePage', () => {
  it('renders settings fields and saves changes', async () => {
    mockApiFetch.mockResolvedValueOnce({
      dpo_name: 'DPO Test',
      dpo_email: 'dpo@test.com',
      dpa_signed: false
    });

    render(<PrivacidadePage />);

    await waitFor(() => {
      expect(screen.getByDisplayValue('DPO Test')).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue('dpo@test.com')).toBeInTheDocument();

    const dpaCheckbox = screen.getByLabelText('Data Processing Agreement (DPA) Assinado');
    expect(dpaCheckbox).not.toBeChecked();

    const user = userEvent.setup();
    await user.click(dpaCheckbox);

    expect(dpaCheckbox).toBeChecked();

    mockApiFetch.mockResolvedValueOnce({}); // mock save response

    const saveButton = screen.getByRole('button', { name: 'Salvar' });
    await user.click(saveButton);

    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/tenant/privacy-settings/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dpo_name: 'DPO Test',
        dpo_email: 'dpo@test.com',
        dpa_signed: true
      })
    });

    await waitFor(() => {
      expect(screen.getByText('Configurações salvas com sucesso.')).toBeInTheDocument();
    });
  });

  it('renders error state on save failure', async () => {
    mockApiFetch.mockResolvedValueOnce({
      dpo_name: '',
      dpo_email: '',
      dpa_signed: false
    });

    render(<PrivacidadePage />);

    await waitFor(() => {
      expect(screen.getByText('Nome do Encarregado (DPO)')).toBeInTheDocument();
    });

    mockApiFetch.mockRejectedValueOnce(new Error('Network error'));

    const user = userEvent.setup();
    const saveButton = screen.getByRole('button', { name: 'Salvar' });
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText('Erro ao salvar as configurações.')).toBeInTheDocument();
    });
  });
});
