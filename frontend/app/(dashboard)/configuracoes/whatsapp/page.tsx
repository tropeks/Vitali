'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, MessageCircle, Phone, CheckCircle, AlertCircle, Clock, Loader2, X } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface HealthStatus {
  status: 'ok' | 'error'
  evolution_api?: {
    state: 'open' | 'connecting' | 'close' | string
    instance?: string
    phone?: string
    last_seen?: string
  }
  detail?: string
}

interface Contact {
  id: string
  phone: string
  patient_name: string | null
  opt_in: boolean
  opt_in_at: string | null
  opt_out_at: string | null
  created_at: string
}

interface MessageLog {
  id: string
  contact: string
  contact_phone: string
  patient_name: string | null
  direction: 'inbound' | 'outbound'
  content_preview: string
  message_type: 'text' | 'button_reply' | 'template'
  appointment: string | null
  created_at: string
}

// ─── Connection tab ───────────────────────────────────────────────────────────

function ConnectionTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [reconnecting, setReconnecting] = useState(false)

  const fetchHealth = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/whatsapp/health/')
      const data = await r.json()
      setHealth(data)
    } catch {
      setHealth({ status: 'error', detail: 'Falha ao conectar com a API.' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
    const interval = setInterval(fetchHealth, 15000)
    return () => clearInterval(interval)
  }, [fetchHealth])

  const handleReconnect = async () => {
    setReconnecting(true)
    try {
      await fetch('/api/v1/whatsapp/setup-webhook/', { method: 'POST' })
      await fetchHealth()
    } catch {
      // ignore
    } finally {
      setReconnecting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm">Verificando conexão...</span>
      </div>
    )
  }

  const state = health?.evolution_api?.state ?? 'close'
  const isConnected = state === 'open'
  const isConnecting = state === 'connecting'
  const isError = health?.status === 'error' || state === 'close'

  return (
    <div className="max-w-lg space-y-6">
      {/* Status card */}
      <div className={`rounded-xl border p-5 ${
        isConnected
          ? 'bg-green-50 border-green-200'
          : isConnecting
          ? 'bg-yellow-50 border-yellow-200'
          : 'bg-red-50 border-red-200'
      }`}>
        <div className="flex items-center gap-3 mb-3">
          {isConnected ? (
            <CheckCircle size={20} className="text-green-600 shrink-0" />
          ) : isConnecting ? (
            <Loader2 size={20} className="text-yellow-600 animate-spin shrink-0" />
          ) : (
            <AlertCircle size={20} className="text-red-600 shrink-0" />
          )}
          <span className={`font-semibold ${
            isConnected ? 'text-green-800' : isConnecting ? 'text-yellow-800' : 'text-red-800'
          }`}>
            {isConnected
              ? 'Conectado'
              : isConnecting
              ? 'Aguardando confirmação...'
              : 'Desconectado'}
          </span>
        </div>

        {isConnected && health?.evolution_api?.phone && (
          <div className="flex items-center gap-2 text-sm text-green-700 mb-2">
            <Phone size={14} />
            <span>{health.evolution_api.phone}</span>
          </div>
        )}

        {isConnected && health?.evolution_api?.last_seen && (
          <div className="flex items-center gap-2 text-xs text-green-600">
            <Clock size={12} />
            <span>Último heartbeat: {new Date(health.evolution_api.last_seen).toLocaleString('pt-BR')}</span>
          </div>
        )}

        {isError && health?.detail && (
          <p className="text-sm text-red-700 mt-1">{health.detail}</p>
        )}

        {isConnecting && (
          <p className="text-sm text-yellow-700 mt-1">
            Escaneie o QR code com o WhatsApp do número da clínica.
          </p>
        )}
      </div>

      {/* QR placeholder when disconnected */}
      {!isConnected && !isConnecting && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-center space-y-3">
          <div className="mx-auto w-40 h-40 bg-slate-100 rounded-lg flex items-center justify-center">
            <MessageCircle size={48} className="text-slate-300" />
          </div>
          <p className="text-sm text-slate-500">
            Inicie a conexão e escaneie o QR code com o WhatsApp da clínica.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={handleReconnect}
          disabled={reconnecting}
          className="flex items-center gap-2 px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={15} className={reconnecting ? 'animate-spin' : ''} />
          {isConnected ? 'Reconectar' : 'Conectar'}
        </button>
      </div>

      <p className="text-xs text-slate-400">
        A URL do webhook é configurada automaticamente ao conectar. Para desenvolvimento local,
        configure um túnel (ngrok) e defina <code className="bg-slate-100 px-1 rounded">WHATSAPP_EVOLUTION_URL</code> no .env.
      </p>
    </div>
  )
}

// ─── Conversations tab ────────────────────────────────────────────────────────

function ConversationsTab() {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)
  const [logs, setLogs] = useState<MessageLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)

  const fetchContacts = useCallback(async (query: string) => {
    try {
      const q = query ? `?search=${encodeURIComponent(query)}` : ''
      const r = await fetch(`/api/v1/whatsapp/contacts/${q}`)
      const d = await r.json()
      setContacts(d.results ?? d)
    } catch {
      setContacts([])
    } finally {
      setLoading(false)
    }
  }, [])

  // Debounce search — fire at most once per 300ms to avoid per-keystroke requests
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchContacts(search), 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [search, fetchContacts])

  const openContact = async (contact: Contact) => {
    setSelectedContact(contact)
    setLogsLoading(true)
    try {
      const r = await fetch(`/api/v1/whatsapp/message-logs/?contact=${contact.id}`)
      const d = await r.json()
      setLogs(d.results ?? d)
    } catch {
      setLogs([])
    } finally {
      setLogsLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm">Carregando conversas...</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <input
        type="text"
        placeholder="Buscar por nome ou telefone..."
        className="w-full max-w-sm px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {contacts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
          <MessageCircle size={40} className="text-slate-200" />
          <p className="text-sm">Nenhuma conversa ainda.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {contacts.map((c) => (
            <button
              key={c.id}
              onClick={() => openContact(c)}
              className="w-full text-left px-4 py-3 bg-white border border-slate-200 rounded-xl hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-slate-900 text-sm">
                    {c.patient_name ?? c.phone}
                  </span>
                  {c.patient_name && (
                    <span className="ml-2 text-xs text-slate-400">{c.phone}</span>
                  )}
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full border ${
                  c.opt_in
                    ? 'bg-green-50 text-green-700 border-green-200'
                    : 'bg-slate-50 text-slate-500 border-slate-200'
                }`}>
                  {c.opt_in ? 'Opt-in' : 'Sem opt-in'}
                </span>
              </div>
              {c.opt_in_at && (
                <p className="text-xs text-slate-400 mt-0.5">
                  Consentimento em {new Date(c.opt_in_at).toLocaleDateString('pt-BR')}
                </p>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Message log modal */}
      {selectedContact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 shrink-0">
              <div>
                <h3 className="font-semibold text-slate-900">
                  {selectedContact.patient_name ?? selectedContact.phone}
                </h3>
                {selectedContact.patient_name && (
                  <p className="text-xs text-slate-400">{selectedContact.phone}</p>
                )}
              </div>
              <button
                onClick={() => setSelectedContact(null)}
                className="text-slate-400 hover:text-slate-700 p-1"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
              {logsLoading ? (
                <div className="flex justify-center py-10">
                  <Loader2 size={20} className="animate-spin text-slate-400" />
                </div>
              ) : logs.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-10">
                  Sem mensagens registradas.
                </p>
              ) : (
                logs.map((log) => (
                  <div
                    key={log.id}
                    className={`flex ${log.direction === 'inbound' ? 'justify-start' : 'justify-end'}`}
                  >
                    <div className={`max-w-xs px-3 py-2 rounded-xl text-xs ${
                      log.direction === 'inbound'
                        ? 'bg-slate-100 text-slate-800'
                        : 'bg-blue-600 text-white'
                    }`}>
                      <p>{log.content_preview}</p>
                      <p className={`mt-1 text-right ${
                        log.direction === 'inbound' ? 'text-slate-400' : 'text-blue-200'
                      }`}>
                        {new Date(log.created_at).toLocaleTimeString('pt-BR', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type Tab = 'conexao' | 'conversas'

export default function WhatsAppSettingsPage() {
  const [tab, setTab] = useState<Tab>('conexao')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">WhatsApp</h1>
        <p className="text-sm text-slate-500 mt-1">
          Configuração da integração WhatsApp e histórico de conversas com pacientes.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200">
        {(['conexao', 'conversas'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors capitalize ${
              tab === t
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {t === 'conexao' ? 'Conexão' : 'Conversas'}
          </button>
        ))}
      </div>

      {tab === 'conexao' ? <ConnectionTab /> : <ConversationsTab />}
    </div>
  )
}
