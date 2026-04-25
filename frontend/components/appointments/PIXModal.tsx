'use client'

/**
 * S-055: PIX payment modal for appointment detail.
 *
 * Mobile-first:
 * - Copy-paste code is primary CTA
 * - QR code is below, collapsed on mobile by default
 * - Polls /api/v1/billing/pix/charges/{id}/ every 5s after charge created
 * - Expiry regeneration button when charge is expired
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { Copy, Check, RefreshCw, X, QrCode, ChevronDown, ChevronUp } from 'lucide-react'

interface PIXCharge {
  id: string
  status: 'pending' | 'paid' | 'expired' | 'cancelled' | 'refunded'
  amount: string
  pix_copy_paste: string
  pix_qr_code_base64: string
  expires_at: string
  paid_at: string | null
}

interface PIXModalProps {
  appointmentId: string
  amount: number
  patientName: string
  onClose: () => void
  onPaid?: () => void
}

const POLL_INTERVAL_MS = 5000

export default function PIXModal({ appointmentId, amount, patientName, onClose, onPaid }: PIXModalProps) {
  const [charge, setCharge] = useState<PIXCharge | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [showQR, setShowQR] = useState(false)
  const [generating, setGenerating] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const createCharge = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch('/api/v1/billing/pix/charges/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ appointment_id: appointmentId, amount }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail ?? body.error ?? `Erro ${r.status}`)
      }
      const data: PIXCharge = await r.json()
      setCharge(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro ao criar cobrança PIX.')
    } finally {
      setLoading(false)
    }
  }, [appointmentId, amount])

  // Create charge on mount
  useEffect(() => {
    createCharge()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [createCharge])

  // Start polling once we have a pending charge
  useEffect(() => {
    if (!charge || charge.status !== 'pending') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    const poll = async () => {
      try {
        const r = await fetch(`/api/v1/billing/pix/charges/${charge.id}/`)
        if (!r.ok) return
        const updated: PIXCharge = await r.json()
        setCharge(updated)
        if (updated.status === 'paid') {
          if (pollRef.current) clearInterval(pollRef.current)
          onPaid?.()
        }
        if (updated.status === 'expired' || updated.status === 'cancelled') {
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        // ignore polling errors
      }
    }

    pollRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    // We deliberately depend on id+status only — restarting on any other charge
    // field change (e.g. transient pix_copy_paste re-renders) would needlessly
    // reset the poll interval.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [charge?.id, charge?.status, onPaid])

  const handleCopy = async () => {
    if (!charge?.pix_copy_paste) return
    try {
      await navigator.clipboard.writeText(charge.pix_copy_paste)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback: select input
    }
  }

  const handleRegenerate = async () => {
    if (pollRef.current) clearInterval(pollRef.current)
    setGenerating(true)
    setCharge(null)
    await createCharge()
    setGenerating(false)
  }

  const expiresAt = charge?.expires_at ? new Date(charge.expires_at) : null
  const isExpired = charge?.status === 'expired' || (expiresAt !== null && expiresAt < new Date())
  const isPaid = charge?.status === 'paid'

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4">
      <div className="bg-white w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div>
            <h2 className="font-semibold text-slate-900">Cobrança PIX</h2>
            <p className="text-xs text-slate-500">{patientName}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1 rounded-lg">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-5 space-y-5">
          {/* Amount */}
          <div className="text-center">
            <p className="text-3xl font-bold text-slate-900">
              {new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(amount)}
            </p>
          </div>

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-8 gap-3 text-slate-400">
              <RefreshCw size={18} className="animate-spin" />
              <span className="text-sm">Gerando cobrança...</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
              <p>{error}</p>
              <button
                onClick={createCharge}
                className="mt-2 text-red-600 font-medium underline"
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* Paid state */}
          {isPaid && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-5 text-center space-y-2">
              <div className="text-4xl">✅</div>
              <p className="font-semibold text-green-800">Pagamento recebido!</p>
              <p className="text-sm text-green-700">A consulta foi confirmada automaticamente.</p>
            </div>
          )}

          {/* Expired state */}
          {isExpired && !isPaid && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center space-y-3">
              <p className="font-semibold text-amber-800">PIX expirado</p>
              <p className="text-sm text-amber-700">O código PIX expirou. Gere um novo para continuar.</p>
              <button
                onClick={handleRegenerate}
                disabled={generating}
                className="flex items-center gap-2 mx-auto px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 disabled:opacity-50"
              >
                <RefreshCw size={14} className={generating ? 'animate-spin' : ''} />
                {generating ? 'Gerando...' : 'Gerar novo PIX'}
              </button>
            </div>
          )}

          {/* Pending: copy-paste + QR */}
          {charge && !isPaid && !isExpired && (
            <>
              {/* Polling indicator */}
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Aguardando pagamento...</span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                  verificando automaticamente
                </span>
              </div>

              {/* Copy-paste — primary CTA */}
              <div>
                <p className="text-xs font-medium text-slate-600 mb-2">PIX Copia e Cola</p>
                <div className="flex gap-2">
                  <input
                    readOnly
                    value={charge.pix_copy_paste}
                    className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-slate-600 overflow-hidden"
                    onClick={(e) => (e.target as HTMLInputElement).select()}
                  />
                  <button
                    onClick={handleCopy}
                    className={`shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      copied
                        ? 'bg-green-600 text-white'
                        : 'bg-blue-600 text-white hover:bg-blue-700'
                    }`}
                  >
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                    {copied ? 'Copiado!' : 'Copiar'}
                  </button>
                </div>
              </div>

              {/* QR Code — collapsed on mobile by default */}
              <div>
                <button
                  onClick={() => setShowQR((v) => !v)}
                  className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700"
                >
                  <QrCode size={14} />
                  QR Code
                  {showQR ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                {showQR && charge.pix_qr_code_base64 && (
                  <div className="mt-3 flex justify-center">
                    {/* base64 data URL — next/image can't optimize these and adds overhead */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`data:image/png;base64,${charge.pix_qr_code_base64}`}
                      alt="QR Code PIX"
                      className="w-48 h-48 border border-slate-200 rounded-xl"
                    />
                  </div>
                )}
              </div>

              {/* Expiry info */}
              {expiresAt && (
                <p className="text-xs text-slate-400 text-center">
                  Válido até {expiresAt.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
