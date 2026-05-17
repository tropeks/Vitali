export type OperationalTone = 'neutral' | 'info' | 'attention' | 'success' | 'critical'

export interface StatusMeta {
  label: string
  badgeClass: string
  borderClass: string
  rowClass: string
  tone: OperationalTone
}

export const APPOINTMENT_STATUS_META: Record<string, StatusMeta> = {
  scheduled: {
    label: 'Agendado',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
    borderClass: 'border-l-slate-300',
    rowClass: 'bg-white',
    tone: 'neutral',
  },
  confirmed: {
    label: 'Confirmado',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
    borderClass: 'border-l-blue-500',
    rowClass: 'bg-blue-50/40',
    tone: 'info',
  },
  waiting: {
    label: 'Aguardando',
    badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200',
    borderClass: 'border-l-yellow-500',
    rowClass: 'bg-yellow-50/50',
    tone: 'attention',
  },
  in_progress: {
    label: 'Em atendimento',
    badgeClass: 'bg-green-100 text-green-800 border-green-200',
    borderClass: 'border-l-green-500',
    rowClass: 'bg-green-50/50',
    tone: 'success',
  },
  completed: {
    label: 'Concluído',
    badgeClass: 'bg-slate-100 text-slate-600 border-slate-200',
    borderClass: 'border-l-slate-300',
    rowClass: 'bg-slate-50/50',
    tone: 'neutral',
  },
  cancelled: {
    label: 'Cancelado',
    badgeClass: 'bg-red-100 text-red-700 border-red-200',
    borderClass: 'border-l-red-500',
    rowClass: 'bg-red-50/40',
    tone: 'critical',
  },
  no_show: {
    label: 'Não compareceu',
    badgeClass: 'bg-red-100 text-red-700 border-red-200',
    borderClass: 'border-l-red-500',
    rowClass: 'bg-red-50/40',
    tone: 'critical',
  },
}

const FALLBACK_STATUS_META: StatusMeta = {
  label: 'Indefinido',
  badgeClass: 'bg-slate-100 text-slate-600 border-slate-200',
  borderClass: 'border-l-slate-300',
  rowClass: 'bg-white',
  tone: 'neutral',
}

export function getAppointmentStatusMeta(status?: string | null): StatusMeta {
  if (!status) return FALLBACK_STATUS_META
  return APPOINTMENT_STATUS_META[status] ?? { ...FALLBACK_STATUS_META, label: status }
}

export interface DashboardOverviewLike {
  appointments_waiting?: number | null
  appointments_confirmed?: number | null
  appointments_cancelled?: number | null
  appointments_no_show?: number | null
  encounters_open?: number | null
  encounters_signed?: number | null
  revenue?: string | number | null
  wait_time_avg_min?: number | null
}

export interface OperationalActionItem {
  id: string
  label: string
  value: string
  detail: string
  href: string
  actionLabel: string
  tone: OperationalTone
}

export function buildDashboardActionQueue(
  overview: DashboardOverviewLike | null | undefined
): OperationalActionItem[] {
  const waiting = overview?.appointments_waiting ?? 0
  const confirmed = overview?.appointments_confirmed ?? 0
  const openEncounters = overview?.encounters_open ?? 0
  const signedEncounters = overview?.encounters_signed ?? 0
  const cancelled = overview?.appointments_cancelled ?? 0
  const noShow = overview?.appointments_no_show ?? 0
  const waitTime = overview?.wait_time_avg_min

  return [
    {
      id: 'waiting-room',
      label: 'Fila assistencial',
      value: String(waiting),
      detail:
        waitTime == null
          ? `${confirmed} confirmados para acompanhar`
          : `Espera média ${Math.round(waitTime)} min`,
      href: '/waiting-room',
      actionLabel: 'Abrir sala',
      tone: waiting > 0 ? 'attention' : 'neutral',
    },
    {
      id: 'open-encounters',
      label: 'Prontuários em aberto',
      value: String(openEncounters),
      detail: `${signedEncounters} consultas assinadas no período`,
      href: '/encounters',
      actionLabel: 'Revisar',
      tone: openEncounters > 0 ? 'attention' : 'success',
    },
    {
      id: 'schedule-quality',
      label: 'Agenda com atrito',
      value: String(cancelled + noShow),
      detail: `${cancelled} canceladas · ${noShow} faltas`,
      href: '/appointments',
      actionLabel: 'Ver agenda',
      tone: cancelled + noShow > 0 ? 'critical' : 'success',
    },
  ]
}

export interface PatientSummaryLike {
  is_active?: boolean | null
  active_allergies_count?: number | null
}

export function summarizePatients(patients: PatientSummaryLike[]) {
  return patients.reduce(
    (acc, patient) => {
      if (patient.is_active === false) {
        acc.inactive += 1
      } else {
        acc.active += 1
      }
      if ((patient.active_allergies_count ?? 0) > 0) {
        acc.withAllergies += 1
      }
      return acc
    },
    { active: 0, inactive: 0, withAllergies: 0 }
  )
}

export function formatPtTime(value?: string | null): string {
  if (!value) return '--:--'
  return new Date(value).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ---------------------------------------------------------------------------
// Canonical status system (single source of truth)
//
// Every workflow status the operational UI renders resolves through one of the
// maps below. Screens must not re-declare status colours inline. `badgeClass`
// is the bordered pill recipe (100-bg / 800-text / 200-border); `tone` maps to
// the soft TONE_CLASSES chip used for non-status signals.
// ---------------------------------------------------------------------------

/** Soft tinted chip used for operational *signals* (not workflow status). */
export const TONE_CLASSES: Record<OperationalTone, string> = {
  neutral: 'border-slate-200 bg-white text-slate-700',
  info: 'border-blue-200 bg-blue-50 text-blue-800',
  attention: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  success: 'border-green-200 bg-green-50 text-green-800',
  critical: 'border-red-200 bg-red-50 text-red-700',
}

export interface BadgeMeta {
  label: string
  badgeClass: string
  tone: OperationalTone
}

function badge(label: string, badgeClass: string, tone: OperationalTone): BadgeMeta {
  return { label, badgeClass, tone }
}

const BADGE_FALLBACK: BadgeMeta = badge(
  'Indefinido',
  'bg-slate-100 text-slate-600 border-slate-200',
  'neutral',
)

/**
 * Resolve any status against a canonical meta map.
 *
 * The canonical label always wins for a *known* status — this is the whole
 * point of a single source of truth and removes the prior drift where the
 * same status rendered with different server `status_display` strings on
 * different screens. `fallbackLabel` (e.g. a server display string) is only
 * used when the status is unknown to the map.
 */
export function resolveBadgeMeta(
  map: Record<string, BadgeMeta>,
  status?: string | null,
  fallbackLabel?: string | null,
): BadgeMeta {
  if (!status) {
    return fallbackLabel ? { ...BADGE_FALLBACK, label: fallbackLabel } : BADGE_FALLBACK
  }
  const meta = map[status]
  if (meta) return meta
  return { ...BADGE_FALLBACK, label: fallbackLabel ?? status }
}

/** TISS guide: draft -> pending -> submitted -> paid / denied -> appeal */
export const GUIDE_STATUS_META: Record<string, BadgeMeta> = {
  draft: badge('Rascunho', 'bg-slate-100 text-slate-600 border-slate-200', 'neutral'),
  pending: badge('Pendente', 'bg-yellow-100 text-yellow-800 border-yellow-200', 'attention'),
  submitted: badge('Enviada', 'bg-blue-100 text-blue-800 border-blue-200', 'info'),
  paid: badge('Paga', 'bg-green-100 text-green-800 border-green-200', 'success'),
  denied: badge('Glosada', 'bg-red-100 text-red-700 border-red-200', 'critical'),
  appeal: badge('Recurso', 'bg-orange-100 text-orange-800 border-orange-200', 'attention'),
}

/**
 * Prescription lifecycle. `signed` is blue ("liberada / acionável"); green is
 * reserved for `dispensed` ("concluída"). This resolves the prior conflict
 * where pharmacy/dispensação rendered `signed` green while the patient command
 * center rendered it blue.
 */
export const PRESCRIPTION_STATUS_META: Record<string, BadgeMeta> = {
  draft: badge('Rascunho', 'bg-slate-100 text-slate-600 border-slate-200', 'neutral'),
  signed: badge('Assinada', 'bg-blue-100 text-blue-800 border-blue-200', 'info'),
  partially_dispensed: badge(
    'Parcial',
    'bg-yellow-100 text-yellow-800 border-yellow-200',
    'attention',
  ),
  dispensed: badge('Dispensada', 'bg-green-100 text-green-800 border-green-200', 'success'),
  cancelled: badge('Cancelada', 'bg-red-100 text-red-700 border-red-200', 'critical'),
}

export const ENCOUNTER_STATUS_META: Record<string, BadgeMeta> = {
  open: badge('Em aberto', 'bg-yellow-100 text-yellow-800 border-yellow-200', 'attention'),
  signed: badge('Assinada', 'bg-green-100 text-green-800 border-green-200', 'success'),
  cancelled: badge('Cancelada', 'bg-red-100 text-red-700 border-red-200', 'critical'),
}

/** Allergy severity rendered as a pill. */
export const ALLERGY_SEVERITY_META: Record<string, BadgeMeta> = {
  life_threatening: badge('Risco de vida', 'bg-red-100 text-red-800 border-red-200', 'critical'),
  severe: badge('Grave', 'bg-orange-100 text-orange-800 border-orange-200', 'critical'),
  moderate: badge('Moderada', 'bg-yellow-100 text-yellow-800 border-yellow-200', 'attention'),
  mild: badge('Leve', 'bg-green-100 text-green-800 border-green-200', 'success'),
}

/** Allergy severity rendered as a tinted *block* (50-bg card tint). */
export const ALLERGY_SEVERITY_BLOCK: Record<string, string> = {
  life_threatening: 'border-red-200 bg-red-50 text-red-800',
  severe: 'border-orange-200 bg-orange-50 text-orange-800',
  moderate: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  mild: 'border-green-200 bg-green-50 text-green-800',
}

export interface StockStatusInput {
  is_expired?: boolean | null
  is_low_stock?: boolean | null
  expiry_date?: string | null
}

/** Derive a stock alert badge from expiry / low-stock signals. */
export function getStockStatusMeta(item: StockStatusInput): BadgeMeta | null {
  if (item.is_expired) {
    return badge('Vencido', 'bg-red-100 text-red-700 border-red-200', 'critical')
  }
  if (item.expiry_date) {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const target = new Date(`${item.expiry_date}T00:00:00`)
    const days = Math.ceil((target.getTime() - today.getTime()) / 86_400_000)
    if (days >= 0 && days <= 30) {
      return badge(`Vence em ${days}d`, 'bg-yellow-100 text-yellow-800 border-yellow-200', 'attention')
    }
  }
  if (item.is_low_stock) {
    return badge('Estoque baixo', 'bg-orange-100 text-orange-700 border-orange-200', 'attention')
  }
  return null
}
