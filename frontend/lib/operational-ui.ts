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
    badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
    borderClass: 'border-l-slate-300',
    rowClass: 'bg-white',
    tone: 'neutral',
  },
  confirmed: {
    label: 'Confirmado',
    badgeClass: 'bg-neu-brand/10 text-neu-brand border-neu-brand/20',
    borderClass: 'border-l-blue-500',
    rowClass: 'bg-blue-50/40',
    tone: 'info',
  },
  waiting: {
    label: 'Aguardando',
    badgeClass: 'bg-neu-warning/10 text-neu-warning border-neu-warning/20',
    borderClass: 'border-l-yellow-500',
    rowClass: 'bg-yellow-50/50',
    tone: 'attention',
  },
  in_progress: {
    label: 'Em atendimento',
    badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20',
    borderClass: 'border-l-green-500',
    rowClass: 'bg-green-50/50',
    tone: 'success',
  },
  completed: {
    label: 'Concluído',
    badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
    borderClass: 'border-l-slate-300',
    rowClass: 'bg-slate-50/50',
    tone: 'neutral',
  },
  cancelled: {
    label: 'Cancelado',
    badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20',
    borderClass: 'border-l-red-500',
    rowClass: 'bg-red-50/40',
    tone: 'critical',
  },
  no_show: {
    label: 'Não compareceu',
    badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20',
    borderClass: 'border-l-red-500',
    rowClass: 'bg-red-50/40',
    tone: 'critical',
  },
}

const FALLBACK_STATUS_META: StatusMeta = {
  label: 'Indefinido',
  badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
  borderClass: 'border-l-slate-300',
  rowClass: 'bg-white',
  tone: 'neutral',
}

export function getAppointmentStatusMeta(status?: string | null): StatusMeta {
  if (!status) return FALLBACK_STATUS_META
  return APPOINTMENT_STATUS_META[status] ?? { ...FALLBACK_STATUS_META, label: status }
}

/**
 * Canonical display label for an appointment status, applying the same
 * single-source-of-truth rule as `resolveBadgeMeta`: the canonical label
 * wins for a *known* status (deterministic, immune to server display drift);
 * the server `statusDisplay` is used only when the status is unknown to the
 * map (so new/custom statuses still render a human label, never a raw key).
 * Every appointment badge — agenda, sala de espera, patient command center —
 * must render through this, never `status_display || meta.label`.
 */
export function appointmentBadgeLabel(
  status?: string | null,
  statusDisplay?: string | null,
): string {
  if (status && APPOINTMENT_STATUS_META[status]) return APPOINTMENT_STATUS_META[status].label
  return statusDisplay || status || FALLBACK_STATUS_META.label
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
// is the bordered pill recipe over the neumorphic tokens (token/10-bg /
// token-text / token/20-border; semantic amber uses `neu-warning`, orange keeps
// the stock Tailwind palette until an orange token exists); `tone` maps to the
// soft TONE_CLASSES chip used for non-status signals.
// ---------------------------------------------------------------------------

/**
 * Soft tinted chip used for operational *signals* (not workflow status).
 *
 * Superfície = tokens neumórficos (`neu-*` de tailwind.config.ts): bg no token
 * /10, borda /20, texto no token. Desvio anotado: não há token laranja no
 * namespace `neu`, então as receitas orange abaixo mantêm a paleta Tailwind
 * padrão até existir um token.
 */
export const TONE_CLASSES: Record<OperationalTone, string> = {
  neutral: 'border-neu-inkMuted/20 bg-white text-neu-inkSoft',
  info: 'border-neu-brand/20 bg-neu-brand/10 text-neu-brand',
  attention: 'border-neu-warning/20 bg-neu-warning/10 text-neu-warning',
  success: 'border-neu-success/20 bg-neu-success/10 text-neu-success',
  critical: 'border-neu-danger/20 bg-neu-danger/10 text-neu-danger',
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
  'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
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
  draft: badge('Rascunho', 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20', 'neutral'),
  pending: badge('Pendente', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention'),
  submitted: badge('Enviada', 'bg-neu-brand/10 text-neu-brand border-neu-brand/20', 'info'),
  paid: badge('Paga', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  denied: badge('Glosada', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
  appeal: badge('Recurso', 'bg-orange-100 text-orange-800 border-orange-200', 'attention'),
}

/**
 * Prescription lifecycle. `signed` is blue ("liberada / acionável"); green is
 * reserved for `dispensed` ("concluída"). This resolves the prior conflict
 * where pharmacy/dispensação rendered `signed` green while the patient command
 * center rendered it blue.
 */
export const PRESCRIPTION_STATUS_META: Record<string, BadgeMeta> = {
  draft: badge('Rascunho', 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20', 'neutral'),
  signed: badge('Assinada', 'bg-neu-brand/10 text-neu-brand border-neu-brand/20', 'info'),
  partially_dispensed: badge(
    'Parcial',
    'bg-neu-warning/10 text-neu-warning border-neu-warning/20',
    'attention',
  ),
  dispensed: badge('Dispensada', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  cancelled: badge('Cancelada', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
}

export const ENCOUNTER_STATUS_META: Record<string, BadgeMeta> = {
  open: badge('Em aberto', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention'),
  signed: badge('Assinada', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  cancelled: badge('Cancelada', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
}

/** Allergy severity rendered as a pill. */
export const ALLERGY_SEVERITY_META: Record<string, BadgeMeta> = {
  life_threatening: badge('Risco de vida', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
  severe: badge('Grave', 'bg-orange-100 text-orange-800 border-orange-200', 'critical'),
  moderate: badge('Moderada', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention'),
  mild: badge('Leve', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
}

/** Allergy severity rendered as a tinted *block* (50-bg card tint). */
export const ALLERGY_SEVERITY_BLOCK: Record<string, string> = {
  life_threatening: 'border-red-200 bg-red-50 text-red-800',
  severe: 'border-orange-200 bg-orange-50 text-orange-800',
  moderate: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  mild: 'border-green-200 bg-green-50 text-green-800',
}

/** Subscription lifecycle — `Subscription.status` on /configuracoes/assinatura. */
export const SUBSCRIPTION_STATUS_META: Record<string, BadgeMeta> = {
  active: badge('Ativo', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  past_due: badge('Em atraso', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
  cancelled: badge('Cancelado', 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20', 'neutral'),
}

/** Employee `employment_status` lifecycle on /rh/funcionarios. */
export const EMPLOYMENT_STATUS_META: Record<string, BadgeMeta> = {
  active: badge('Ativo', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  on_leave: badge('Afastado', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention'),
  terminated: badge('Desligado', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
}

/** Evolution API connection state from /api/v1/whatsapp/health/ — open/connecting/close. */
export const WA_CONNECTION_STATUS_META: Record<string, BadgeMeta> = {
  open: badge('Conectado', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success'),
  connecting: badge('Aguardando', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention'),
  close: badge('Desconectado', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical'),
}

/**
 * Derived-boolean adapters — small helpers for cases where the underlying
 * field is a boolean rather than a status enum (cadastro ativo, DPA assinado,
 * MFA habilitado, WhatsApp opt-in). They route through the canonical tone
 * vocabulary so call sites never inline status colours.
 */
export function getActivenessMeta(isActive: boolean | null | undefined): BadgeMeta {
  return isActive
    ? badge('Ativo', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success')
    : badge('Inativo', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical')
}

export function getDpaStatusMeta(isSigned: boolean | null | undefined): BadgeMeta {
  return isSigned
    ? badge('DPA assinado', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success')
    : badge('DPA não assinado', 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention')
}

export function getMfaStatusMeta(isActive: boolean | null | undefined): BadgeMeta {
  return isActive
    ? badge('Ativo', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success')
    : badge('Inativo', 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20', 'neutral')
}

export function getOptInMeta(optedIn: boolean | null | undefined): BadgeMeta {
  return optedIn
    ? badge('Opt-in', 'bg-neu-success/10 text-neu-success border-neu-success/20', 'success')
    : badge('Sem opt-in', 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20', 'neutral')
}

export interface StockStatusInput {
  is_expired?: boolean | null
  is_low_stock?: boolean | null
  expiry_date?: string | null
}

/** Derive a stock alert badge from expiry / low-stock signals. */
export function getStockStatusMeta(item: StockStatusInput): BadgeMeta | null {
  if (item.is_expired) {
    return badge('Vencido', 'bg-neu-danger/10 text-neu-danger border-neu-danger/20', 'critical')
  }
  if (item.expiry_date) {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const target = new Date(`${item.expiry_date}T00:00:00`)
    const days = Math.ceil((target.getTime() - today.getTime()) / 86_400_000)
    if (days >= 0 && days <= 30) {
      return badge(`Vence em ${days}d`, 'bg-neu-warning/10 text-neu-warning border-neu-warning/20', 'attention')
    }
  }
  if (item.is_low_stock) {
    return badge('Estoque baixo', 'bg-orange-100 text-orange-700 border-orange-200', 'attention')
  }
  return null
}
