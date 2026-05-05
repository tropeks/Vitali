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
