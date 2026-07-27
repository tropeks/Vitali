/**
 * Centro Cirúrgico (C5) — shared types and enum→label maps for the surgical
 * chart surface (Cirurgia tab on the patient chart).
 *
 * Shapes mirror `backend/apps/emr/serializers_surgery.py` and the
 * `SurgicalCaseViewSet.timeline` action EXACTLY. Note the API-shape reality:
 * `SurgicalCaseSerializer` returns *pk ids* for `surgeon` / `operating_room`
 * (not nested objects), so the panel resolves the room name client-side via
 * `/operating-rooms/` and lists procedures via `/surgical-procedures/?case=`.
 * All ids are strings. The append-only `times` / `checklists` and the `team`
 * come from the single `GET /surgical-cases/{id}/timeline/` action.
 */

/** DRF paginated envelope, tolerated alongside a bare array. */
export interface ListResponse<T> {
  results?: T[]
  count?: number
  next?: string | null
}

export function normalizeList<T>(payload: ListResponse<T> | T[] | null | undefined): T[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

/** Surgical case (caso cirúrgico) — pk-based FKs, exactly as the serializer emits. */
export interface SurgicalCase {
  id: string
  patient: string
  surgeon: string
  operating_room?: string | null
  encounter?: string | null
  admission?: string | null
  scheduled_start?: string | null
  scheduled_end?: string | null
  priority: string
  status: string
  anesthesia_type?: string | null
  notes?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** Planned procedure (TUSS) of a case (`/surgical-procedures/?case=`). */
export interface SurgicalProcedure {
  id: string
  case: string
  tuss_code?: string | null
  tuss_code_value?: string | null
  quantity?: number | null
  laterality?: string | null
  notes?: string | null
}

/** Append-only intra-op time entry (read-only surface). */
export interface SurgicalTimeEntry {
  id: string
  case: string
  event: string
  recorded_at?: string | null
  recorded_by?: string | null
  notes?: string | null
  created_at?: string | null
}

/** Confirmed WHO safe-surgery checklist phase (append-only per phase). */
export interface SurgicalChecklistEntry {
  id: string
  case: string
  phase: string
  items: Record<string, boolean>
  confirmed_at?: string | null
  confirmed_by?: string | null
  created_at?: string | null
}

/** A team member of a case, in a given role. `professional_name` from output. */
export interface SurgicalTeamMemberEntry {
  id: string
  case: string
  professional: string
  professional_name?: string | null
  role: string
  notes?: string | null
  created_at?: string | null
}

/** `GET /surgical-cases/{id}/timeline/` — the intra-op prontuário of a case. */
export interface CaseTimeline {
  case: string
  status: string
  times: SurgicalTimeEntry[]
  checklists: SurgicalChecklistEntry[]
  team: SurgicalTeamMemberEntry[]
}

/** Operating room option (`/operating-rooms/`) — id → "code — name" resolution. */
export interface OperatingRoomOption {
  id: string
  code: string
  name: string
}

/** Professional option for the team picker (`/professionals/?search=`). */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  specialty?: string | null
  council_number?: string | null
}

// ─── enum → label maps (mirror surgery_models TextChoices) ────────────────────

export const CASE_STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  agendada: { label: 'Agendada', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  confirmada: { label: 'Confirmada', badgeClass: 'border-blue-200 bg-blue-50 text-blue-700' },
  em_sala: { label: 'Em sala', badgeClass: 'border-indigo-200 bg-indigo-50 text-indigo-700' },
  em_andamento: { label: 'Em andamento', badgeClass: 'border-amber-200 bg-amber-50 text-amber-800' },
  finalizada: { label: 'Finalizada', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  cancelada: { label: 'Cancelada', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
}

export const CASE_PRIORITY_META: Record<string, { label: string; badgeClass: string }> = {
  eletiva: { label: 'Eletiva', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  urgencia: { label: 'Urgência', badgeClass: 'border-amber-200 bg-amber-50 text-amber-800' },
  emergencia: { label: 'Emergência', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
}

/** The 6 intra-op events, in the canonical (chronological) order. */
export const TIME_EVENT_ORDER: Array<{ value: string; label: string }> = [
  { value: 'sala_entrada', label: 'Entrada na sala' },
  { value: 'anestesia_inicio', label: 'Início da anestesia' },
  { value: 'anestesia_fim', label: 'Fim da anestesia' },
  { value: 'incisao', label: 'Incisão' },
  { value: 'fechamento', label: 'Fechamento' },
  { value: 'sala_saida', label: 'Saída da sala' },
]

/** The 3 WHO checklist phases with their default confirmable items. */
export const CHECKLIST_PHASES: Array<{
  value: string
  label: string
  items: Array<{ key: string; label: string }>
}> = [
  {
    value: 'sign_in',
    label: 'Sign in (antes da anestesia)',
    items: [
      { key: 'identidade_confirmada', label: 'Identidade do paciente confirmada' },
      { key: 'sitio_marcado', label: 'Sítio cirúrgico marcado' },
      { key: 'anestesia_verificada', label: 'Equipamento de anestesia verificado' },
      { key: 'alergia_verificada', label: 'Alergias verificadas' },
    ],
  },
  {
    value: 'time_out',
    label: 'Time out (antes da incisão)',
    items: [
      { key: 'equipe_apresentada', label: 'Equipe apresentada (nome e função)' },
      { key: 'confirmacao_verbal', label: 'Confirmação verbal de paciente/sítio/procedimento' },
      { key: 'antibiotico_profilatico', label: 'Antibiótico profilático nos últimos 60 min' },
    ],
  },
  {
    value: 'sign_out',
    label: 'Sign out (antes de sair da sala)',
    items: [
      { key: 'contagem_instrumentais', label: 'Contagem de instrumentais/compressas confere' },
      { key: 'identificacao_amostras', label: 'Amostras identificadas' },
      { key: 'problemas_equipamento', label: 'Problemas de equipamento revisados' },
    ],
  },
]

export const TEAM_ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'cirurgiao', label: 'Cirurgião' },
  { value: 'primeiro_auxiliar', label: 'Primeiro auxiliar' },
  { value: 'anestesista', label: 'Anestesista' },
  { value: 'instrumentador', label: 'Instrumentador' },
  { value: 'circulante', label: 'Circulante' },
  { value: 'outro', label: 'Outro' },
]

export function labelOf(
  options: Array<{ value: string; label: string }>,
  value?: string | null,
): string {
  if (!value) return '—'
  return options.find((option) => option.value === value)?.label ?? value
}

/** pt-BR date/time formatter shared by the surgery components. */
export function formatDateTime(value?: string | null): string {
  if (!value) return 'Não informado'
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
