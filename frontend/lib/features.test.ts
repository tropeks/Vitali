import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getActiveModules } from './features';
import { apiFetch } from './api';

vi.mock('./api', () => ({ apiFetch: vi.fn() }));

describe('getActiveModules', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the tenant features endpoint as its authority', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ active_modules: ['emr', 'billing'] });

    await expect(getActiveModules()).resolves.toEqual(['emr', 'billing']);
    expect(apiFetch).toHaveBeenCalledWith('/api/v1/features/');
  });

  it('rejects with the API instead of converting an outage into no modules', async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error('offline'));
    await expect(getActiveModules()).rejects.toThrow('offline');
  });
});
