'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

export function CookieBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const consent = localStorage.getItem('vitali_cookie_consent');
    if (!consent) {
      setShow(true);
    }
  }, []);

  const acceptCookies = () => {
    localStorage.setItem('vitali_cookie_consent', 'true');
    setShow(false);
  };

  if (!show) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 p-2 bg-neu-panel border-t border-neu-app text-neu-ink flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-sans shadow-[0_-2px_4px_rgba(0,0,0,0.05)]">
      <div className="pl-4">
        <strong>Aviso de Privacidade:</strong> Este sistema EMR utiliza cookies estritamente necessários para autenticação e auditoria clínica. Ao continuar, você concorda com a nossa{' '}
        <Link href="/privacidade" className="font-semibold text-neu-brand hover:underline">
          Política de Privacidade
        </Link>.
      </div>
      <div className="pr-4 pb-1 sm:pb-0 shrink-0">
        <button
          onClick={acceptCookies}
          className="px-4 py-1 bg-neu-brand hover:bg-neu-brandDeep text-white border border-neu-brandDeep rounded-sm font-semibold transition-colors"
        >
          Ciente e de acordo
        </button>
      </div>
    </div>
  );
}
