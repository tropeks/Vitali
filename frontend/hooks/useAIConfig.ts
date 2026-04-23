'use client';

import { useState, useEffect } from 'react';
import { getAccessToken } from '@/lib/auth';

const CACHE_KEY = 'vitali_ai_config';
const TTL_MS = 5 * 60 * 1000; // 5 minutes

interface AIConfigData {
  ai_scribe_enabled: boolean;
  is_signed: boolean;
}

interface CacheEntry {
  data: AIConfigData;
  expiresAt: number;
}

function readCache(): AIConfigData | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() > entry.expiresAt) {
      sessionStorage.removeItem(CACHE_KEY);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

function writeCache(data: AIConfigData): void {
  try {
    const entry: CacheEntry = { data, expiresAt: Date.now() + TTL_MS };
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch {
    // sessionStorage unavailable — continue without caching
  }
}

let inflight: Promise<AIConfigData | null> | null = null;

async function fetchAIConfig(): Promise<AIConfigData | null> {
  const cached = readCache();
  if (cached) return cached;

  if (!inflight) {
    const token = getAccessToken();
    inflight = fetch('/api/v1/settings/dpa/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (res) => {
        if (!res.ok) {
          inflight = null;
          return null;
        }
        const body = await res.json();
        const data: AIConfigData = {
          ai_scribe_enabled: !!body.ai_scribe_enabled,
          is_signed: !!body.is_signed,
        };
        writeCache(data);
        inflight = null;
        return data;
      })
      .catch(() => {
        inflight = null;
        return null;
      });
  }

  return inflight;
}

/**
 * useAIConfig()
 *
 * Reads tenant-level AI config from /api/v1/settings/dpa/.
 * Used to gate AI UI surfaces so they never render when the backend
 * would 404/403 on click.
 *
 * Fail-CLOSED: on loading or error, scribeReady=false. Hiding a button
 * is safer than showing one that will fail.
 */
export function useAIConfig(): { scribeReady: boolean; loading: boolean } {
  const [data, setData] = useState<AIConfigData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const cached = readCache();
    if (cached) {
      setData(cached);
      setLoading(false);
      return;
    }

    fetchAIConfig().then((d) => {
      if (!cancelled) {
        setData(d);
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const scribeReady = !!(data && data.ai_scribe_enabled && data.is_signed);
  return { scribeReady, loading };
}
