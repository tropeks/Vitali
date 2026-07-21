import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModuleGate } from './ModuleGate';
import { useActiveModules } from '@/hooks/useHasModule';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }));
vi.mock('@/hooks/useHasModule', () => ({ useActiveModules: vi.fn() }));

describe('ModuleGate', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders content when the authoritative module list permits it', () => {
    vi.mocked(useActiveModules).mockReturnValue(['emr', 'billing']);
    render(<ModuleGate module="billing"><div>Faturamento</div></ModuleGate>);
    expect(screen.getByText('Faturamento')).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('redirects without rendering protected module content when disabled', async () => {
    vi.mocked(useActiveModules).mockReturnValue(['emr']);
    render(<ModuleGate module="billing"><div>Faturamento</div></ModuleGate>);
    expect(screen.queryByText('Faturamento')).not.toBeInTheDocument();
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  });
});
