'use client';

import { useState, useEffect } from 'react';
import { getActiveModules } from '@/lib/features';

const CACHE_KEY = 'vitali_active_modules';
const TTL_MS = 5 * 60 * 1000; // 5 minutes

interface CacheEntry {
  modules: string[];
  expiresAt: number;
}

function readCache(): string[] | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() > entry.expiresAt) {
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
    const entry: CacheEntry = { modules, expiresAt: Date.now() + TTL_MS };
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
        // Fail-open: return a sentinel that makes all modules available
        return ['__fail_open__'];
      });
  }

  return inflight;
}

/**
 * useHasModule(moduleKey)
 *
 * Returns true if the tenant has the given module enabled.
 * - Caches the result in sessionStorage for 5 minutes.
 * - Fail-open: returns true on network error or while loading (no layout shift).
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

  // While loading OR on error (sentinel), return true (fail-open)
  if (modules === null) return true;
  if (modules.includes('__fail_open__')) return true;

  return modules.includes(moduleKey);
}

/**
 * useActiveModules()
 *
 * Returns the full set of active module keys for the current tenant.
 * - Fail-open: returns null while loading (callers treat null as "all visible").
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
  if (modules.includes('__fail_open__')) return null; // treat as "all visible"
  return modules;
}
