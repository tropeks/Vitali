'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useTranslations } from 'next-intl';

export function CookieBanner() {
  const t = useTranslations('cookieBanner');
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
    <div className="fixed bottom-0 left-0 right-0 z-50 p-2 bg-[#F4F6F8] border-t border-[#D0D7DE] text-[#24292F] flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-sans shadow-[0_-2px_4px_rgba(0,0,0,0.05)]">
      <div className="pl-4">
        <strong>{t('noticeLabel')}</strong>{' '}
        {t.rich('body', {
          policy: (chunks) => (
            <Link href="/privacidade" className="font-semibold text-[#0066A1] hover:underline">
              {chunks}
            </Link>
          ),
        })}
      </div>
      <div className="pr-4 pb-1 sm:pb-0 shrink-0">
        <button
          onClick={acceptCookies}
          className="px-4 py-1 bg-[#0066A1] hover:bg-[#004b7a] text-white border border-[#004b7a] rounded-sm font-semibold transition-colors"
        >
          {t('accept')}
        </button>
      </div>
    </div>
  );
}
