export const CLINICAL_WORKSPACE_STORAGE_KEY = 'vitali:clinical-workspace-tabs'

export const MAX_CLINICAL_WORKSPACE_TABS = 8

export interface ClinicalWorkspaceTab {
  encounterId: string
  patientName: string
  medicalRecordNumber: string
  status: string
  statusDisplay: string
  lastOpenedAt: string
}

function isWorkspaceTab(value: unknown): value is ClinicalWorkspaceTab {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.encounterId === 'string' &&
    candidate.encounterId.length > 0 &&
    typeof candidate.patientName === 'string' &&
    candidate.patientName.length > 0 &&
    typeof candidate.medicalRecordNumber === 'string' &&
    typeof candidate.status === 'string' &&
    typeof candidate.statusDisplay === 'string' &&
    typeof candidate.lastOpenedAt === 'string'
  )
}

export function parseClinicalWorkspaceTabs(raw: string | null | undefined): ClinicalWorkspaceTab[] {
  if (!raw) return []

  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isWorkspaceTab).slice(0, MAX_CLINICAL_WORKSPACE_TABS)
  } catch {
    return []
  }
}

export function upsertClinicalWorkspaceTab(
  tabs: ClinicalWorkspaceTab[],
  next: ClinicalWorkspaceTab
): ClinicalWorkspaceTab[] {
  const withoutCurrent = tabs.filter((tab) => tab.encounterId !== next.encounterId)
  return [next, ...withoutCurrent].slice(0, MAX_CLINICAL_WORKSPACE_TABS)
}

export function removeClinicalWorkspaceTab(
  tabs: ClinicalWorkspaceTab[],
  encounterId: string
): ClinicalWorkspaceTab[] {
  return tabs.filter((tab) => tab.encounterId !== encounterId)
}
