'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useActiveModules } from '@/hooks/useHasModule';

interface ModuleGateProps {
  module: string;
  children: React.ReactNode;
  fallbackHref?: string;
}

/** Route-level counterpart to the module-aware menu, backed by FeatureFlag. */
export function ModuleGate({ module, children, fallbackHref = '/dashboard' }: ModuleGateProps) {
  const router = useRouter();
  const activeModules = useActiveModules();
  const allowed = activeModules?.includes(module) ?? false;

  useEffect(() => {
    if (activeModules !== null && !allowed) router.replace(fallbackHref);
  }, [activeModules, allowed, fallbackHref, router]);

  if (activeModules === null || !allowed) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sm text-neu-inkMuted">
        Verificando acesso ao módulo…
      </div>
    );
  }

  return <>{children}</>;
}
