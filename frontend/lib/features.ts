import { apiFetch } from '@/lib/api';

export async function getActiveModules(): Promise<string[]> {
  const data = await apiFetch<{ active_modules?: unknown }>('/api/v1/features/');
  if (!Array.isArray(data.active_modules)) return [];
  return data.active_modules.filter((module): module is string => typeof module === 'string');
}
