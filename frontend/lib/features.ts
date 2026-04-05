import { getAccessToken } from '@/lib/auth';

export async function getActiveModules(): Promise<string[]> {
  const token = getAccessToken();
  if (!token) return [];
  try {
    const res = await fetch('/api/v1/features/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.active_modules ?? [];
  } catch {
    return [];
  }
}
