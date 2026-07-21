'use client';

import { useState, useEffect } from 'react';
import { getActiveModules } from '@/lib/features';

const CACHE_KEY = 'vitali_active_modules';
const TTL_MS = 5 * 60 * 1000; // 5 minutes

interface CacheEntry {
  modules: string[];
  expiresAt: number;
  subject: string | null;
}

function currentSubject(): string | null {
  if (typeof document === 'undefined') return null;
  const raw = document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('vitali_user='))
    ?.slice('vitali_user='.length);
  if (!raw) return null;
  try {
    const user = JSON.parse(decodeURIComponent(raw));
    return user?.id == null ? null : String(user.id);
  } catch {
    return null;
  }
}

function readCache(): string[] | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() > entry.expiresAt || entry.subject !== currentSubject()) {
      sessionStorage.removeItem(CACHE_KEY);
      return null;
    }
    return entry.modules;
  } catch {
    return null;
  }
}

function writeCache(modules: string[]): void {
  try {
    const entry: CacheEntry = {
      modules,
      expiresAt: Date.now() + TTL_MS,
      subject: currentSubject(),
    };
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch {
    // sessionStorage unavailable — continue without caching
  }
}

// Shared promise so concurrent calls only hit the API once
let inflight: Promise<string[]> | null = null;

async function fetchModules(): Promise<string[]> {
  const cached = readCache();
  if (cached) return cached;

  if (!inflight) {
    inflight = getActiveModules()
      .then((modules) => {
        writeCache(modules);
        inflight = null;
        return modules;
      })
      .catch(() => {
        inflight = null;
        // FeatureFlag is the authority. On an unavailable API, do not expose
        // module UI based on the stale login-cookie snapshot.
        return ['__unavailable__'];
      });
  }

  return inflight;
}

/**
 * useHasModule(moduleKey)
 *
 * Returns true if the tenant has the given module enabled.
 * - Caches the result in sessionStorage for 5 minutes.
 * - Returns false on API failure; backend permissions remain the final guard.
 */
export function useHasModule(moduleKey: string): boolean {
  // null = loading; string[] = resolved
  const [modules, setModules] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Try synchronous cache first (avoids any async flicker)
    const cached = readCache();
    if (cached) {
      setModules(cached);
      return;
    }

    fetchModules().then((m) => {
      if (!cancelled) setModules(m);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  // Keep existing items stable while loading, then fail closed on API failure.
  if (modules === null) return true;
  if (modules.includes('__unavailable__')) return false;

  return modules.includes(moduleKey);
}

/**
 * useActiveModules()
 *
 * Returns the full set of active module keys for the current tenant.
 * - Returns null while loading and [] when the authoritative API is unavailable.
 * - Uses the same cache and dedup logic as useHasModule.
 */
export function useActiveModules(): string[] | null {
  const [modules, setModules] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    const cached = readCache();
    if (cached) {
      setModules(cached);
      return;
    }

    fetchModules().then((m) => {
      if (!cancelled) setModules(m);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  if (modules === null) return null;
  if (modules.includes('__unavailable__')) return [];
  return modules;
}
