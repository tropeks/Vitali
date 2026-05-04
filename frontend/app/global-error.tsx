'use client'

import * as Sentry from '@sentry/nextjs'
import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    Sentry.captureException(error)
  }, [error])

  return (
    <html lang="pt-BR">
      <body>
        <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
          <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-sm font-medium text-red-600">Erro inesperado</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900">
              Não foi possível carregar esta tela.
            </h1>
            <p className="mt-3 text-sm text-slate-600">
              O erro foi registrado para análise. Tente novamente ou volte para o dashboard.
            </p>
            {error.digest && (
              <p className="mt-3 rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-500">
                {error.digest}
              </p>
            )}
            <div className="mt-5 flex gap-3">
              <button
                type="button"
                onClick={reset}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Tentar novamente
              </button>
              <a
                href="/dashboard"
                className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900"
              >
                Dashboard
              </a>
            </div>
          </section>
        </main>
      </body>
    </html>
  )
}
