'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, MessageCircle, Phone, Clock, Loader2, X } from 'lucide-react'
import { PageShell, SectionState, StatusBadge, Button } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import {
  WA_CONNECTION_STATUS_META,
  getOptInMeta,
  resolveBadgeMeta,
} from '@/lib/operational-ui'

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
      const data = await apiFetch<HealthStatus>('/api/v1/whatsapp/health/')
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
      await apiFetch('/api/v1/whatsapp/setup-webhook/', { method: 'POST' })
      await fetchHealth()
    } catch {
      // ignore
    } finally {
      setReconnecting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-neu-inkMuted">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-sm">Verificando conexão...</span>
      </div>
    )
  }

  const state = health?.evolution_api?.state ?? 'close'
  const connectionMeta = resolveBadgeMeta(WA_CONNECTION_STATUS_META, state)
  const isConnected = state === 'open'
  const isConnecting = state === 'connecting'
  const tone =
    connectionMeta.tone === 'success'
      ? 'success'
      : connectionMeta.tone === 'attention'
        ? 'warning'
        : 'critical'

  const detail = (() => {
    if (health?.status === 'error' && health.detail) return health.detail
    if (isConnecting) return 'Escaneie o QR code com o WhatsApp do número da clínica.'
    if (isConnected) {
      const lines: string[] = []
      if (health?.evolution_api?.phone) lines.push(`Número: ${health.evolution_api.phone}`)
      if (health?.evolution_api?.last_seen) {
        lines.push(
          `Último heartbeat: ${new Date(health.evolution_api.last_seen).toLocaleString('pt-BR')}`
        )
      }
      return lines.join(' · ') || 'Integração saudável.'
    }
    return 'Conecte uma instância do WhatsApp para começar a enviar mensagens.'
  })()

  return (
    <div className="max-w-lg space-y-5">
      <section className="bg-neu-panel rounded-xl shadow-neu-panel border border-white">
        <div className="border-b border-neu-app/50 px-4 py-3 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-neu-ink">Integração Evolution API</h2>
          <StatusBadge meta={connectionMeta} />
        </div>
        <div className="p-4 space-y-3">
          <SectionState
            title={connectionMeta.label}
            detail={detail}
            tone={tone}
            action={
              <div className="flex items-center gap-2 flex-wrap">
                {isConnected && health?.evolution_api?.phone && (
                  <span className="inline-flex items-center gap-1 text-xs text-neu-ink">
                    <Phone size={12} />
                    {health.evolution_api.phone}
                  </span>
                )}
                {isConnected && health?.evolution_api?.last_seen && (
                  <span className="inline-flex items-center gap-1 text-xs text-neu-inkMuted">
                    <Clock size={12} />
                    {new Date(health.evolution_api.last_seen).toLocaleString('pt-BR')}
                  </span>
                )}
              </div>
            }
          />
          <Button
            variant="secondary"
            onClick={handleReconnect}
            disabled={reconnecting}
            className="inline-flex items-center gap-2"
          >
            <RefreshCw size={15} className={reconnecting ? 'animate-spin' : ''} />
            {isConnected ? 'Reconectar' : 'Conectar'}
          </Button>
        </div>
      </section>

      {!isConnected && !isConnecting && (
        <div className="bg-neu-panel rounded-xl shadow-neu-panel border border-white p-6 text-center space-y-3">
          <div className="mx-auto w-40 h-40 bg-neu-input rounded-lg shadow-neu-inset flex items-center justify-center">
            <MessageCircle size={48} className="text-neu-inkMuted" />
          </div>
          <p className="text-sm text-neu-ink">
            Inicie a conexão e escaneie o QR code com o WhatsApp da clínica.
          </p>
        </div>
      )}

      <p className="text-xs text-neu-inkMuted">
        A URL do webhook é configurada automaticamente ao conectar. Para desenvolvimento local,
        configure um túnel (ngrok) e defina{' '}
        <code className="bg-neu-input text-neu-ink px-1 rounded font-mono">WHATSAPP_EVOLUTION_URL</code> no
        .env.
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
      const d = await apiFetch<{ results?: Contact[] } | Contact[]>(`/api/v1/whatsapp/contacts/${q}`)
      setContacts(Array.isArray(d) ? d : (d.results ?? []))
    } catch {
      setContacts([])
    } finally {
      setLoading(false)
    }
  }, [])

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
      const d = await apiFetch<{ results?: MessageLog[] } | MessageLog[]>(`/api/v1/whatsapp/message-logs/?contact=${contact.id}`)
      setLogs(Array.isArray(d) ? d : (d.results ?? []))
    } catch {
      setLogs([])
    } finally {
      setLogsLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-neu-inkMuted">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-sm">Carregando conversas...</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <input
        type="text"
        placeholder="Buscar por nome ou telefone..."
        className="neu-input max-w-sm placeholder-neu-inkMuted"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {contacts.length === 0 ? (
        <SectionState
          title="Nenhuma conversa ainda."
          detail="Conversas aparecerão aqui assim que pacientes interagirem com o WhatsApp."
        />
      ) : (
        <div className="space-y-2">
          {contacts.map((c) => (
            <button
              key={c.id}
              onClick={() => openContact(c)}
              className="w-full text-left px-4 py-3 bg-neu-panel border border-white shadow-neu-panel rounded-lg hover:bg-neu-panelAlt transition-colors"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <span className="font-medium text-neu-ink text-sm">
                    {c.patient_name ?? c.phone}
                  </span>
                  {c.patient_name && (
                    <span className="ml-2 font-mono text-xs text-neu-inkMuted">{c.phone}</span>
                  )}
                </div>
                <StatusBadge meta={getOptInMeta(c.opt_in)} />
              </div>
              {c.opt_in_at && (
                <p className="text-xs text-neu-inkMuted mt-1">
                  Consentimento em {new Date(c.opt_in_at).toLocaleDateString('pt-BR')}
                </p>
              )}
            </button>
          ))}
        </div>
      )}

      {selectedContact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-neu-outer rounded-lg shadow-neu-modal w-full max-w-lg max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-neu-app/50 shrink-0">
              <div>
                <h3 className="text-base font-semibold text-neu-ink">
                  {selectedContact.patient_name ?? selectedContact.phone}
                </h3>
                {selectedContact.patient_name && (
                  <p className="text-xs font-mono text-neu-inkMuted">{selectedContact.phone}</p>
                )}
              </div>
              <button
                onClick={() => setSelectedContact(null)}
                className="text-neu-inkMuted hover:text-neu-ink p-1"
                aria-label="Fechar"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
              {logsLoading ? (
                <div className="flex justify-center py-10">
                  <Loader2 size={18} className="animate-spin text-neu-inkMuted" />
                </div>
              ) : logs.length === 0 ? (
                <p className="text-sm text-neu-inkMuted text-center py-10">
                  Sem mensagens registradas.
                </p>
              ) : (
                logs.map((log) => (
                  <div
                    key={log.id}
                    className={`flex ${log.direction === 'inbound' ? 'justify-start' : 'justify-end'}`}
                  >
                    <div
                      className={`max-w-xs px-3 py-2 rounded-lg text-xs ${
                        log.direction === 'inbound'
                          ? 'bg-neu-input text-neu-ink'
                          : 'bg-neu-brand text-white'
                      }`}
                    >
                      <p>{log.content_preview}</p>
                      <p
                        className={`mt-1 text-right ${
                          log.direction === 'inbound' ? 'text-neu-inkMuted' : 'text-white/70'
                        }`}
                      >
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
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">WhatsApp</h1>
        <p className="text-sm text-neu-inkSoft mt-1">
          Configuração da integração WhatsApp e histórico de conversas com pacientes.
        </p>
      </div>

      <div className="flex border-b border-slate-200">
        {(['conexao', 'conversas'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors capitalize ${
              tab === t
                ? 'border-neu-brand text-neu-brand'
                : 'border-transparent text-neu-inkMuted hover:text-neu-ink'
            }`}
          >
            {t === 'conexao' ? 'Conexão' : 'Conversas'}
          </button>
        ))}
      </div>

      {tab === 'conexao' ? <ConnectionTab /> : <ConversationsTab />}
    </PageShell>
  )
}
