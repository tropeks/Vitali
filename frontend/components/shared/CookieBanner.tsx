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
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4 bg-gray-900 text-white shadow-lg flex flex-col sm:flex-row items-center justify-between gap-4">
      <div className="text-sm">
        Nós usamos cookies para melhorar sua experiência. Ao continuar navegando, você concorda com a nossa{' '}
        <Link href="/privacidade" className="underline text-blue-400 hover:text-blue-300">
          Política de Privacidade
        </Link>.
      </div>
      <button
        onClick={acceptCookies}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium whitespace-nowrap"
      >
        Aceitar
      </button>
    </div>
  );
}
