'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  FileText,
  HeartPulse,
  IdCard,
  Pill,
  Receipt,
  RefreshCw,
  ShieldAlert,
  Stethoscope,
  UserRound,
  WalletCards,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  ALLERGY_SEVERITY_BLOCK,
  ENCOUNTER_STATUS_META,
  GUIDE_STATUS_META,
  PRESCRIPTION_STATUS_META,
  getAppointmentStatusMeta,
  resolveBadgeMeta,
  type BadgeMeta,
} from '@/lib/operational-ui'
import { PageShell, SectionState, StatusBadge } from '@/components/shared'

type TabId = 'resumo' | 'timeline' | 'clinico' | 'convenios' | 'dados'

interface Patient {
  id: string
  medical_record_number?: string | null
  full_name: string
  social_name?: string | null
  cpf_masked?: string | null
  birth_date?: string | null
  age?: number | null
  gender?: string | null
  gender_display?: string | null
  blood_type?: string | null
  phone?: string | null
  whatsapp?: string | null
  email?: string | null
  address?: Record<string, any> | null
  emergency_contact?: Record<string, any> | null
  notes?: string | null
  is_active?: boolean | null
  allergies?: Allergy[]
  medical_history?: MedicalHistory[]
  created_at?: string | null
  updated_at?: string | null
}

interface Allergy {
  id: string
  substance: string
  reaction?: string | null
  severity: string
  severity_display?: string | null
  status: string
  status_display?: string | null
  created_at?: string | null
}

interface MedicalHistory {
  id: string
  condition: string
  cid10_code?: string | null
  type: string
  type_display?: string | null
  status: string
  status_display?: string | null
  onset_date?: string | null
  notes?: string | null
}

interface InsuranceCard {
  id: number
  provider_ans_code: string
  provider_name: string
  card_number: string
  valid_until?: string | null
  is_active: boolean
  created_at?: string | null
}

interface TimelineEvent {
  type: string
  id: string
  date?: string | null
  status?: string | null
  professional?: string | null
  chief_complaint?: string | null
}

interface Appointment {
  id: string
  patient_name?: string | null
  patient_mrn?: string | null
  professional_name?: string | null
  start_time?: string | null
  end_time?: string | null
  duration_minutes?: number | null
  type?: string | null
  type_display?: string | null
  status?: string | null
  status_display?: string | null
  notes?: string | null
  arrived_at?: string | null
  started_at?: string | null
}

interface Encounter {
  id: string
  professional_name?: string | null
  encounter_date?: string | null
  status?: string | null
  status_display?: string | null
  chief_complaint?: string | null
}

interface Prescription {
  id: string
  status?: string | null
  status_display?: string | null
  is_signed?: boolean | null
  signed_at?: string | null
  prescriber_name?: string | null
  notes?: string | null
  items?: Array<{
    id: string
    drug_name?: string | null
    quantity?: string | number | null
    unit_of_measure?: string | null
  }>
  created_at?: string | null
}

interface TissGuide {
  id: string
  guide_number?: string | null
  guide_type_display?: string | null
  provider_name?: string | null
  status?: string | null
  status_display?: string | null
  competency?: string | null
  total_value?: string | number | null
  updated_at?: string | null
}

interface ListResponse<T> {
  results?: T[]
  count?: number
}

interface RelatedState {
  insurance: InsuranceCard[]
  timeline: TimelineEvent[]
  appointments: Appointment[]
  encounters: Encounter[]
  prescriptions: Prescription[]
  guides: TissGuide[]
}

const EMPTY_RELATED: RelatedState = {
  insurance: [],
  timeline: [],
  appointments: [],
  encounters: [],
  prescriptions: [],
  guides: [],
}

const emptyCard = {
  provider_ans_code: '',
  provider_name: '',
  card_number: '',
  valid_until: '',
  is_active: true,
}

function normalizeList<T>(payload: ListResponse<T> | T[] | null | undefined): T[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

function formatDate(value?: string | null) {
  if (!value) return 'Não informado'
  return new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR')
}

function formatDateTime(value?: string | null) {
  if (!value) return 'Não informado'
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatShortDateTime(value?: string | null) {
  if (!value) return 'Sem agenda'
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatMoney(value?: string | number | null) {
  const numberValue = Number(value ?? 0)
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  }).format(Number.isFinite(numberValue) ? numberValue : 0)
}

/** Ad-hoc derived badge (active/inactive, history state) — domain workflow
 *  statuses must use the canonical maps via resolveBadgeMeta instead. */
function statusBadge(meta?: { label: string; className: string }, fallback?: string | null) {
  const label = meta?.label ?? fallback ?? 'Indefinido'
  const badgeClass = meta?.className ?? 'border-slate-200 bg-slate-50 text-slate-600'
  return <StatusBadge meta={{ label, badgeClass }} />
}

function badgeFor(map: Record<string, BadgeMeta>, status?: string | null, display?: string | null) {
  return <StatusBadge meta={resolveBadgeMeta(map, status, display)} />
}

function Field({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-slate-900">{value || 'Não informado'}</dd>
    </div>
  )
}

function InsuranceTab({
  patientId,
  initialCards,
  onCardsChanged,
}: {
  patientId: string
  initialCards: InsuranceCard[]
  onCardsChanged: (cards: InsuranceCard[]) => void
}) {
  const [cards, setCards] = useState<InsuranceCard[]>(initialCards)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...emptyCard })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setCards(initialCards)
  }, [initialCards])

  const syncCards = useCallback((nextCards: InsuranceCard[]) => {
    setCards(nextCards)
    onCardsChanged(nextCards)
  }, [onCardsChanged])

  const reload = useCallback(async () => {
    const nextCards = await apiFetch<InsuranceCard[]>(`/api/v1/patients/${patientId}/insurance/`)
    syncCards(nextCards)
  }, [patientId, syncCards])

  const openNew = () => {
    setForm({ ...emptyCard })
    setEditId(null)
    setShowForm(true)
    setError('')
  }

  const openEdit = (card: InsuranceCard) => {
    setForm({
      provider_ans_code: card.provider_ans_code,
      provider_name: card.provider_name,
      card_number: card.card_number,
      valid_until: card.valid_until ?? '',
      is_active: card.is_active,
    })
    setEditId(card.id)
    setShowForm(true)
    setError('')
  }

  const save = async () => {
    if (!form.provider_ans_code || !form.provider_name || !form.card_number) {
      setError('Código ANS, operadora e carteirinha são obrigatórios.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const body = { ...form, valid_until: form.valid_until || null }
      if (editId) {
        await apiFetch(`/api/v1/patients/${patientId}/insurance/${editId}/`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        })
      } else {
        await apiFetch(`/api/v1/patients/${patientId}/insurance/`, {
          method: 'POST',
          body: JSON.stringify(body),
        })
      }
      setShowForm(false)
      await reload()
    } catch {
      setError('Não foi possível salvar o convênio. Revise os dados e tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  const deactivate = async (card: InsuranceCard) => {
    if (!confirm(`Desativar carteirinha ${card.provider_name}?`)) return
    try {
      await apiFetch(`/api/v1/patients/${patientId}/insurance/${card.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: false }),
      })
      await reload()
    } catch {
      setError('Não foi possível desativar o convênio.')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Cobertura e carteirinhas</h2>
          <p className="mt-1 text-sm text-slate-500">
            Convênio visível para agenda, faturamento e autorização TISS.
          </p>
        </div>
        <button
          onClick={openNew}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        >
          <WalletCards size={15} />
          Adicionar convênio
        </button>
      </div>

      {showForm && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">
                {editId ? 'Editar carteirinha' : 'Nova carteirinha'}
              </h3>
              <p className="mt-1 text-xs text-blue-700">
                Campos obrigatórios alimentam o contexto de autorização e cobrança.
              </p>
            </div>
          </div>
          {error && <p className="mt-3 text-sm font-medium text-red-700">{error}</p>}
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <label className="block">
              <span className="text-xs font-semibold text-slate-700">Código ANS *</span>
              <input
                value={form.provider_ans_code}
                onChange={(event) => setForm((current) => ({ ...current, provider_ans_code: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs font-semibold text-slate-700">Operadora *</span>
              <input
                value={form.provider_name}
                onChange={(event) => setForm((current) => ({ ...current, provider_name: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-700">Válida até</span>
              <input
                type="date"
                value={form.valid_until}
                onChange={(event) => setForm((current) => ({ ...current, valid_until: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs font-semibold text-slate-700">Número da carteirinha *</span>
              <input
                value={form.card_number}
                onChange={(event) => setForm((current) => ({ ...current, card_number: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="flex items-center gap-2 pt-6 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
                className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
              Convênio ativo
            </label>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Cancelar
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Salvar convênio'}
            </button>
          </div>
        </div>
      )}

      {cards.length === 0 ? (
        <SectionState
          title="Sem convênio cadastrado"
          detail="Agenda e faturamento podem seguir como particular, mas a guia TISS exigirá cobertura."
          tone="warning"
        />
      ) : (
        <>
          <div className="hidden overflow-hidden rounded-lg border border-slate-200 md:block">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-slate-100 bg-slate-50">
                <tr>
                  {['Status', 'Operadora', 'ANS', 'Carteirinha', 'Validade', 'Ações'].map((heading) => (
                    <th key={heading} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {cards.map((card) => (
                  <tr key={card.id}>
                    <td className="px-4 py-3">
                      {statusBadge(
                        card.is_active
                          ? { label: 'Ativo', className: 'border-green-200 bg-green-50 text-green-700' }
                          : { label: 'Inativo', className: 'border-slate-200 bg-slate-50 text-slate-500' }
                      )}
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-900">{card.provider_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{card.provider_ans_code}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{card.card_number}</td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(card.valid_until)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-3">
                        <button onClick={() => openEdit(card)} className="text-xs font-semibold text-blue-600 hover:underline">
                          Editar
                        </button>
                        {card.is_active && (
                          <button onClick={() => deactivate(card)} className="text-xs font-semibold text-red-600 hover:underline">
                            Desativar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-2 md:hidden">
            {cards.map((card) => (
              <div key={card.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">{card.provider_name}</p>
                    <p className="mt-1 font-mono text-xs text-slate-500">ANS {card.provider_ans_code}</p>
                  </div>
                  {statusBadge(
                    card.is_active
                      ? { label: 'Ativo', className: 'border-green-200 bg-green-50 text-green-700' }
                      : { label: 'Inativo', className: 'border-slate-200 bg-slate-50 text-slate-500' }
                  )}
                </div>
                <div className="mt-3 space-y-1 text-xs text-slate-600">
                  <p className="font-mono">{card.card_number}</p>
                  <p>Validade: {formatDate(card.valid_until)}</p>
                </div>
                <div className="mt-3 flex gap-3">
                  <button onClick={() => openEdit(card)} className="text-xs font-semibold text-blue-600">
                    Editar
                  </button>
                  {card.is_active && (
                    <button onClick={() => deactivate(card)} className="text-xs font-semibold text-red-600">
                      Desativar
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default function PatientDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [patient, setPatient] = useState<Patient | null>(null)
  const [related, setRelated] = useState<RelatedState>(EMPTY_RELATED)
  const [loading, setLoading] = useState(true)
  const [relatedLoading, setRelatedLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [degradedResources, setDegradedResources] = useState<string[]>([])
  const [activeTab, setActiveTab] = useState<TabId>('resumo')

  const loadPatient = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setRelatedLoading(false)
    setError(null)
    setDegradedResources([])
    setRelated(EMPTY_RELATED)

    try {
      const patientData = await apiFetch<Patient>(`/api/v1/patients/${id}/`)
      setPatient(patientData)
      setLoading(false)
      setRelatedLoading(true)

      const [
        insuranceResult,
        timelineResult,
        appointmentsResult,
        encountersResult,
        prescriptionsResult,
        guidesResult,
      ] = await Promise.allSettled([
        apiFetch<InsuranceCard[]>(`/api/v1/patients/${id}/insurance/`),
        apiFetch<{ events?: TimelineEvent[] }>(`/api/v1/patients/${id}/timeline/`),
        apiFetch<ListResponse<Appointment> | Appointment[]>(`/api/v1/appointments/?patient_id=${id}&ordering=start_time`),
        apiFetch<ListResponse<Encounter> | Encounter[]>(`/api/v1/encounters/?patient_id=${id}`),
        apiFetch<ListResponse<Prescription> | Prescription[]>(`/api/v1/prescriptions/?patient=${id}`),
        apiFetch<ListResponse<TissGuide> | TissGuide[]>(`/api/v1/billing/guides/?patient=${id}`),
      ])

      const nextRelated: RelatedState = {
        insurance: insuranceResult.status === 'fulfilled' ? insuranceResult.value : [],
        timeline: timelineResult.status === 'fulfilled' ? timelineResult.value.events ?? [] : [],
        appointments: appointmentsResult.status === 'fulfilled' ? normalizeList(appointmentsResult.value) : [],
        encounters: encountersResult.status === 'fulfilled' ? normalizeList(encountersResult.value) : [],
        prescriptions: prescriptionsResult.status === 'fulfilled' ? normalizeList(prescriptionsResult.value) : [],
        guides: guidesResult.status === 'fulfilled' ? normalizeList(guidesResult.value) : [],
      }

      const degraded = [
        insuranceResult.status === 'rejected' ? 'convênios' : null,
        timelineResult.status === 'rejected' ? 'timeline' : null,
        appointmentsResult.status === 'rejected' ? 'agenda' : null,
        encountersResult.status === 'rejected' ? 'consultas' : null,
        prescriptionsResult.status === 'rejected' ? 'prescrições' : null,
        guidesResult.status === 'rejected' ? 'faturamento' : null,
      ].filter(Boolean) as string[]

      setRelated(nextRelated)
      setDegradedResources(degraded)
    } catch {
      setPatient(null)
      setError('Não foi possível carregar o paciente. Verifique a sessão e tente novamente.')
      setLoading(false)
    } finally {
      setRelatedLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadPatient()
  }, [loadPatient])

  const activeAllergies = useMemo(
    () => patient?.allergies?.filter((allergy) => allergy.status === 'active') ?? [],
    [patient]
  )
  const lifeThreateningAllergies = activeAllergies.filter((allergy) => allergy.severity === 'life_threatening')
  const activeConditions = patient?.medical_history?.filter((item) => item.status === 'active') ?? []
  const activeCards = related.insurance.filter((card) => card.is_active)
  const nextAppointment = related.appointments
    .filter((appointment) => appointment.start_time)
    .sort((a, b) => new Date(a.start_time ?? 0).getTime() - new Date(b.start_time ?? 0).getTime())[0]
  const openEncounters = related.encounters.filter((encounter) => encounter.status === 'open')
  const pendingGuides = related.guides.filter((guide) => guide.status && !['paid'].includes(guide.status))
  const glosaGuides = related.guides.filter((guide) => guide.status === 'denied' || guide.status === 'appeal')
  const activePrescriptions = related.prescriptions.filter((rx) =>
    ['signed', 'partially_dispensed', 'draft'].includes(rx.status ?? '')
  )

  const riskTone = lifeThreateningAllergies.length > 0
    ? 'critical'
    : activeAllergies.length > 0 || activeConditions.length > 0
      ? 'warning'
      : 'success'

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: 'resumo', label: 'Resumo operacional' },
    { id: 'timeline', label: `Timeline${related.timeline.length ? ` (${related.timeline.length})` : ''}` },
    { id: 'clinico', label: `Clínico${activeAllergies.length ? ` (${activeAllergies.length})` : ''}` },
    { id: 'convenios', label: `Convênios${activeCards.length ? ` (${activeCards.length})` : ''}` },
    { id: 'dados', label: 'Dados cadastrais' },
  ]

  if (loading) {
    return (
      <PageShell variant="operational">
        <div className="h-40 animate-pulse rounded-lg bg-slate-100" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-24 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
        <div className="h-80 animate-pulse rounded-lg bg-slate-100" />
      </PageShell>
    )
  }

  if (error || !patient) {
    return (
      <PageShell variant="operational">
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-800">
        <div className="flex items-start gap-3">
          <AlertTriangle size={20} className="mt-0.5" />
          <div>
            <h1 className="text-lg font-semibold">Paciente indisponível</h1>
            <p className="mt-1 text-sm">{error ?? 'Paciente não encontrado.'}</p>
            <button
              onClick={loadPatient}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold text-white hover:bg-red-800"
            >
              <RefreshCw size={15} />
              Tentar novamente
            </button>
          </div>
        </div>
      </div>
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-4 lg:p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <button
                onClick={() => router.back()}
                className="mt-1 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label="Voltar"
              >
                <ArrowLeft size={18} />
              </button>
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-blue-100 text-lg font-bold text-blue-700">
                {patient.full_name.slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Command Center do Paciente
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold text-slate-900">{patient.full_name}</h1>
                  {statusBadge(
                    patient.is_active === false
                      ? { label: 'Cadastro inativo', className: 'border-slate-200 bg-slate-50 text-slate-500' }
                      : { label: 'Cadastro ativo', className: 'border-green-200 bg-green-50 text-green-700' }
                  )}
                </div>
                {patient.social_name && (
                  <p className="mt-1 text-sm font-medium text-slate-600">Nome social: {patient.social_name}</p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                  <span className="font-mono text-xs font-semibold text-slate-700">
                    {patient.medical_record_number || 'Prontuário não gerado'}
                  </span>
                  <span className="text-slate-300">|</span>
                  <span>{patient.age != null ? `${patient.age} anos` : 'Idade não informada'}</span>
                  <span className="text-slate-300">|</span>
                  <span>{patient.gender_display ?? patient.gender ?? 'Gênero não informado'}</span>
                  {patient.blood_type && (
                    <>
                      <span className="text-slate-300">|</span>
                      <span className="font-semibold text-red-700">Tipo {patient.blood_type}</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[620px]">
              <button
                onClick={() => router.push('/appointments')}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
              >
                <CalendarPlus size={15} />
                Agendar
              </button>
              <button
                onClick={() => router.push('/encounters')}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Stethoscope size={15} />
                Consulta
              </button>
              <button
                onClick={() => router.push('/billing/guides/new')}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Receipt size={15} />
                Guia TISS
              </button>
              <button
                onClick={() => router.push('/farmacia/dispense')}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                <Pill size={15} />
                Farmácia
              </button>
            </div>
          </div>

          {lifeThreateningAllergies.length > 0 && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-800">
              <ShieldAlert size={17} className="mt-0.5 shrink-0" />
              Alergia com risco de vida: {lifeThreateningAllergies.map((allergy) => allergy.substance).join(', ')}
            </div>
          )}

          {degradedResources.length > 0 && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
              <AlertTriangle size={17} className="mt-0.5 shrink-0" />
              Dados parciais: {degradedResources.join(', ')} indisponível(is). O prontuário principal continua acessível.
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-0 divide-y divide-slate-100 lg:grid-cols-4 lg:divide-x lg:divide-y-0">
          <div className="p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <ShieldAlert size={14} />
              Risco clínico
            </div>
            <p className={`mt-2 text-xl font-semibold ${riskTone === 'critical' ? 'text-red-700' : riskTone === 'warning' ? 'text-yellow-700' : 'text-green-700'}`}>
              {riskTone === 'critical' ? 'Risco crítico' : riskTone === 'warning' ? 'Atenção ativa' : 'Sem alerta ativo'}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {activeAllergies.length} alergia(s) ativa(s) | {activeConditions.length} condição(ões) ativa(s)
            </p>
          </div>
          <div className="p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <WalletCards size={14} />
              Cobertura
            </div>
            <p className="mt-2 truncate text-xl font-semibold text-slate-900">
              {activeCards[0]?.provider_name ?? 'Particular/sem convênio'}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {activeCards[0] ? `ANS ${activeCards[0].provider_ans_code}` : 'Guia TISS exigirá cadastro de convênio'}
            </p>
          </div>
          <div className="p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <CalendarClock size={14} />
              Próxima agenda
            </div>
            <p className="mt-2 text-xl font-semibold text-slate-900">
              {nextAppointment ? formatShortDateTime(nextAppointment.start_time) : 'Sem agenda'}
            </p>
            <p className="mt-1 truncate text-xs text-slate-500">
              {nextAppointment?.professional_name ?? 'Nenhum compromisso futuro carregado'}
            </p>
          </div>
          <div className="p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <ClipboardList size={14} />
              Pendências
            </div>
            <p className="mt-2 text-xl font-semibold text-slate-900">
              {openEncounters.length + pendingGuides.length + activePrescriptions.length}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {openEncounters.length} consulta(s) | {pendingGuides.length} guia(s) | {activePrescriptions.length} receita(s)
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(340px,0.85fr)]">
        <main className="space-y-5">
          <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-4 py-3">
              <nav className="flex gap-5 overflow-x-auto">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`shrink-0 border-b-2 px-1 py-3 text-sm font-semibold ${
                      activeTab === tab.id
                        ? 'border-blue-600 text-blue-700'
                        : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </nav>
            </div>

            <div className="p-4 lg:p-5">
              {activeTab === 'resumo' && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    <SectionState
                      title={lifeThreateningAllergies.length > 0 ? 'Bloqueio clínico crítico' : 'Risco clínico monitorado'}
                      detail={
                        lifeThreateningAllergies.length > 0
                          ? 'Validar alergia antes de prescrição, procedimento ou dispensação.'
                          : `${activeAllergies.length} alergia(s) e ${activeConditions.length} condição(ões) ativas.`
                      }
                      tone={riskTone}
                    />
                    <SectionState
                      title={activeCards.length > 0 ? 'Convênio operacional' : 'Cobertura pendente'}
                      detail={activeCards[0] ? `${activeCards[0].provider_name} disponível para TISS.` : 'Cadastrar convênio antes de faturar por operadora.'}
                      tone={activeCards.length > 0 ? 'success' : 'warning'}
                    />
                    <SectionState
                      title={relatedLoading ? 'Sincronizando módulos' : 'Jornada carregada'}
                      detail={relatedLoading ? 'Buscando agenda, consultas, prescrições e faturamento.' : `${related.encounters.length} consulta(s), ${related.guides.length} guia(s), ${related.prescriptions.length} receita(s).`}
                      tone={degradedResources.length > 0 ? 'warning' : 'success'}
                    />
                  </div>

                  <div>
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <h2 className="text-base font-semibold text-slate-900">Fluxo operacional do paciente</h2>
                        <p className="mt-1 text-sm text-slate-500">
                          Agenda, atendimento e continuidade sem voltar para listas globais.
                        </p>
                      </div>
                    </div>
                    <div className="hidden overflow-hidden rounded-lg border border-slate-200 md:block">
                      <table className="w-full text-sm">
                        <thead className="border-b border-slate-100 bg-slate-50">
                          <tr>
                            {['Evento', 'Responsável e data', 'Status', 'Ação'].map((heading) => (
                              <th key={heading} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                                {heading}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 bg-white">
                          {related.appointments.slice(0, 4).map((appointment) => {
                            const meta = getAppointmentStatusMeta(appointment.status)
                            return (
                              <tr key={`appointment-${appointment.id}`} className="hover:bg-blue-50">
                                <td className="px-4 py-3 font-semibold text-slate-900">Agenda</td>
                                <td className="px-4 py-3 text-slate-600">
                                  <p>{appointment.professional_name || 'Profissional não informado'}</p>
                                  <p className="mt-1 text-xs text-slate-500">{formatDateTime(appointment.start_time)}</p>
                                </td>
                                <td className="px-4 py-3">
                                  <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}>
                                    {appointment.status_display ?? meta.label}
                                  </span>
                                </td>
                                <td className="px-4 py-3">
                                  <button onClick={() => router.push('/appointments')} className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline">
                                    Abrir agenda
                                    <ChevronRight size={13} />
                                  </button>
                                </td>
                              </tr>
                            )
                          })}
                          {related.encounters.slice(0, 4).map((encounter) => (
                            <tr key={`encounter-${encounter.id}`} className="hover:bg-blue-50">
                              <td className="px-4 py-3 font-semibold text-slate-900">Consulta</td>
                              <td className="px-4 py-3 text-slate-600">
                                <p>{encounter.professional_name || 'Profissional não informado'}</p>
                                <p className="mt-1 text-xs text-slate-500">{formatDateTime(encounter.encounter_date)}</p>
                              </td>
                              <td className="px-4 py-3">{badgeFor(ENCOUNTER_STATUS_META, encounter.status, encounter.status_display)}</td>
                              <td className="px-4 py-3">
                                <button onClick={() => router.push(`/encounters/${encounter.id}`)} className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline">
                                  Abrir consulta
                                  <ChevronRight size={13} />
                                </button>
                              </td>
                            </tr>
                          ))}
                          {related.appointments.length === 0 && related.encounters.length === 0 && (
                            <tr>
                              <td colSpan={5} className="px-4 py-10 text-center">
                                <p className="font-semibold text-slate-700">Sem agenda ou consulta vinculada.</p>
                                <p className="mt-1 text-sm text-slate-500">Agende o paciente para iniciar a jornada assistencial.</p>
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <div className="space-y-2 md:hidden">
                      {related.appointments.slice(0, 4).map((appointment) => {
                        const meta = getAppointmentStatusMeta(appointment.status)
                        return (
                          <div key={`appointment-mobile-${appointment.id}`} className="rounded-lg border border-slate-200 bg-white p-4">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <p className="text-sm font-semibold text-slate-900">Agenda</p>
                                <p className="mt-1 text-xs text-slate-500">{appointment.professional_name || 'Profissional não informado'}</p>
                              </div>
                              <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}>
                                {appointment.status_display ?? meta.label}
                              </span>
                            </div>
                            <p className="mt-3 text-sm text-slate-700">{formatDateTime(appointment.start_time)}</p>
                            <button onClick={() => router.push('/appointments')} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-blue-600">
                              Abrir agenda
                              <ChevronRight size={13} />
                            </button>
                          </div>
                        )
                      })}
                      {related.encounters.slice(0, 4).map((encounter) => (
                        <div key={`encounter-mobile-${encounter.id}`} className="rounded-lg border border-slate-200 bg-white p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">Consulta</p>
                              <p className="mt-1 text-xs text-slate-500">{encounter.professional_name || 'Profissional não informado'}</p>
                            </div>
                            {badgeFor(ENCOUNTER_STATUS_META, encounter.status, encounter.status_display)}
                          </div>
                          <p className="mt-3 text-sm text-slate-700">{formatDateTime(encounter.encounter_date)}</p>
                          {encounter.chief_complaint && (
                            <p className="mt-2 line-clamp-2 text-xs text-slate-500">{encounter.chief_complaint}</p>
                          )}
                          <button onClick={() => router.push(`/encounters/${encounter.id}`)} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-blue-600">
                            Abrir consulta
                            <ChevronRight size={13} />
                          </button>
                        </div>
                      ))}
                      {related.appointments.length === 0 && related.encounters.length === 0 && (
                        <SectionState
                          title="Sem agenda ou consulta vinculada"
                          detail="Agende o paciente para iniciar a jornada assistencial."
                        />
                      )}
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'timeline' && (
                <div className="space-y-3">
                  {related.timeline.length === 0 ? (
                    <SectionState title="Timeline sem eventos" detail="Consultas assinadas e eventos clínicos aparecerão aqui." />
                  ) : related.timeline.map((event) => (
                    <button
                      key={`${event.type}-${event.id}`}
                      onClick={() => event.type === 'encounter' && router.push(`/encounters/${event.id}`)}
                      className="w-full rounded-lg border border-slate-200 bg-white p-4 text-left hover:bg-blue-50"
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">
                            Consulta com {event.professional || 'profissional não informado'}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">{formatDateTime(event.date)}</p>
                        </div>
                        {badgeFor(ENCOUNTER_STATUS_META, event.status, event.status)}
                      </div>
                      {event.chief_complaint && <p className="mt-3 line-clamp-2 text-sm text-slate-600">{event.chief_complaint}</p>}
                    </button>
                  ))}
                </div>
              )}

              {activeTab === 'clinico' && (
                <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">Alergias e reações</h2>
                    <div className="mt-3 space-y-2">
                      {(patient.allergies ?? []).length === 0 ? (
                        <SectionState title="Sem alergia registrada" detail="Registrar alergias melhora segurança da prescrição e dispensação." tone="success" />
                      ) : patient.allergies?.map((allergy) => (
                        <div key={allergy.id} className={`rounded-lg border px-4 py-3 ${ALLERGY_SEVERITY_BLOCK[allergy.severity] ?? 'border-slate-200 bg-slate-50 text-slate-700'}`}>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold">{allergy.substance}</p>
                              {allergy.reaction && <p className="mt-1 text-xs opacity-80">{allergy.reaction}</p>}
                            </div>
                            <span className="text-xs font-semibold">{allergy.severity_display ?? allergy.severity}</span>
                          </div>
                          <p className="mt-2 text-xs opacity-80">Status: {allergy.status_display ?? allergy.status}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">Histórico e condições</h2>
                    <div className="mt-3 space-y-2">
                      {(patient.medical_history ?? []).length === 0 ? (
                        <SectionState title="Sem histórico registrado" detail="Condições ativas aparecerão como contexto clínico permanente." />
                      ) : patient.medical_history?.map((history) => (
                        <div key={history.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">{history.condition}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                {history.type_display ?? history.type}
                                {history.cid10_code ? ` | CID ${history.cid10_code}` : ''}
                              </p>
                            </div>
                            {statusBadge(
                              history.status === 'active'
                                ? { label: history.status_display ?? 'Ativa', className: 'border-red-200 bg-red-50 text-red-700' }
                                : history.status === 'controlled'
                                  ? { label: history.status_display ?? 'Controlada', className: 'border-yellow-200 bg-yellow-50 text-yellow-800' }
                                  : { label: history.status_display ?? 'Resolvida', className: 'border-green-200 bg-green-50 text-green-700' }
                            )}
                          </div>
                          {history.notes && <p className="mt-2 text-sm text-slate-600">{history.notes}</p>}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'convenios' && (
                <InsuranceTab
                  patientId={id}
                  initialCards={related.insurance}
                  onCardsChanged={(cards) => setRelated((current) => ({ ...current, insurance: cards }))}
                />
              )}

              {activeTab === 'dados' && (
                <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <section>
                    <h2 className="text-base font-semibold text-slate-900">Identificação</h2>
                    <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="CPF" value={patient.cpf_masked ?? '***.***.***-**'} />
                      <Field label="Nascimento" value={formatDate(patient.birth_date)} />
                      <Field label="Gênero" value={patient.gender_display ?? patient.gender} />
                      <Field label="Tipo sanguíneo" value={patient.blood_type} />
                      <Field label="Criado em" value={formatDateTime(patient.created_at)} />
                      <Field label="Atualizado em" value={formatDateTime(patient.updated_at)} />
                    </dl>
                  </section>
                  <section>
                    <h2 className="text-base font-semibold text-slate-900">Contato e endereço</h2>
                    <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="Telefone" value={patient.phone} />
                      <Field label="WhatsApp" value={patient.whatsapp} />
                      <Field label="E-mail" value={patient.email} />
                      <Field
                        label="Contato de emergência"
                        value={patient.emergency_contact?.name ?? patient.emergency_contact?.phone}
                      />
                    </dl>
                    <div className="mt-4">
                      <Field
                        label="Endereço"
                        value={
                          patient.address?.street
                            ? `${patient.address.street}, ${patient.address.number ?? 's/n'} - ${patient.address.city ?? ''}/${patient.address.state ?? ''}`
                            : null
                        }
                      />
                    </div>
                    {patient.notes && (
                      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Observações</p>
                        <p className="mt-1 text-sm text-slate-700">{patient.notes}</p>
                      </div>
                    )}
                  </section>
                </div>
              )}
            </div>
          </div>
        </main>

        <aside className="space-y-5">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <HeartPulse size={17} className="text-red-600" />
              <h2 className="text-base font-semibold text-slate-900">Contexto permanente</h2>
            </div>
            <div className="mt-4 space-y-3">
              <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">Alergias ativas</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {activeAllergies.length ? activeAllergies.map((item) => item.substance).join(', ') : 'Sem alerta registrado'}
                  </p>
                </div>
                <span className="text-lg font-semibold text-slate-900">{activeAllergies.length}</span>
              </div>
              <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">Condições ativas</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {activeConditions.length ? activeConditions.map((item) => item.condition).join(', ') : 'Sem condição ativa'}
                  </p>
                </div>
                <span className="text-lg font-semibold text-slate-900">{activeConditions.length}</span>
              </div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">Contato prioritário</p>
                  <p className="mt-1 text-xs text-slate-500">{patient.phone || patient.whatsapp || 'Não informado'}</p>
                </div>
                <IdCard size={18} className="text-slate-400" />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Receipt size={17} className="text-blue-600" />
              <h2 className="text-base font-semibold text-slate-900">Faturamento</h2>
            </div>
            <div className="mt-4 space-y-3">
              {related.guides.length === 0 ? (
                <SectionState title="Sem guia TISS" detail="Nenhuma guia vinculada ao paciente foi carregada." />
              ) : related.guides.slice(0, 4).map((guide) => (
                <button
                  key={guide.id}
                  onClick={() => router.push(`/billing/guides/${guide.id}`)}
                  className="w-full border-b border-slate-100 pb-3 text-left last:border-b-0 last:pb-0"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {guide.guide_number || 'Guia sem número'}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {guide.provider_name || 'Operadora não informada'} | {formatMoney(guide.total_value)}
                      </p>
                    </div>
                    {badgeFor(GUIDE_STATUS_META, guide.status, guide.status_display)}
                  </div>
                </button>
              ))}
              {glosaGuides.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
                  {glosaGuides.length} guia(s) com glosa/recurso exigem revisão.
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Pill size={17} className="text-blue-600" />
              <h2 className="text-base font-semibold text-slate-900">Prescrições</h2>
            </div>
            <div className="mt-4 space-y-3">
              {related.prescriptions.length === 0 ? (
                <SectionState title="Sem prescrição" detail="Receitas assinadas aparecerão para dispensação." />
              ) : related.prescriptions.slice(0, 4).map((rx) => (
                <div key={rx.id} className="border-b border-slate-100 pb-3 last:border-b-0 last:pb-0">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">
                        {rx.items?.length ?? 0} item(ns) prescritos
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {rx.prescriber_name || 'Prescritor não informado'} | {formatDateTime(rx.signed_at ?? rx.created_at)}
                      </p>
                    </div>
                    {badgeFor(PRESCRIPTION_STATUS_META, rx.status, rx.status_display)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <FileText size={17} className="text-blue-600" />
              <h2 className="text-base font-semibold text-slate-900">Ações rápidas</h2>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-2">
              <button onClick={() => router.push('/appointments')} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                Agendar retorno
                <CalendarPlus size={15} />
              </button>
              <button onClick={() => router.push('/encounters')} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                Abrir consulta
                <Stethoscope size={15} />
              </button>
              <button onClick={() => router.push('/billing/guides/new')} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                Criar guia TISS
                <Receipt size={15} />
              </button>
            </div>
          </div>
        </aside>
      </div>
    </PageShell>
  )
}
