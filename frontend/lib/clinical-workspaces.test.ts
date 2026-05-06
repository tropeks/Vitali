import { describe, expect, it } from 'vitest'
import {
  MAX_CLINICAL_WORKSPACE_TABS,
  parseClinicalWorkspaceTabs,
  removeClinicalWorkspaceTab,
  upsertClinicalWorkspaceTab,
  type ClinicalWorkspaceTab,
} from './clinical-workspaces'

const tab = (id: string): ClinicalWorkspaceTab => ({
  encounterId: id,
  patientName: `Paciente ${id}`,
  medicalRecordNumber: `MRN-${id}`,
  status: 'open',
  statusDisplay: 'Aberta',
  lastOpenedAt: `2026-05-06T10:00:0${id}.000Z`,
})

describe('clinical-workspaces', () => {
  it('parses only valid persisted clinical workspace tabs', () => {
    const parsed = parseClinicalWorkspaceTabs(JSON.stringify([
      tab('1'),
      { encounterId: '', patientName: 'Sem id' },
      null,
      { ...tab('2'), medicalRecordNumber: 123 },
    ]))

    expect(parsed).toEqual([tab('1')])
  })

  it('returns an empty list for corrupted localStorage payloads', () => {
    expect(parseClinicalWorkspaceTabs('{bad json')).toEqual([])
    expect(parseClinicalWorkspaceTabs(JSON.stringify({ encounterId: '1' }))).toEqual([])
  })

  it('keeps the latest encounter first and limits the workspace tab count', () => {
    const initial = Array.from({ length: MAX_CLINICAL_WORKSPACE_TABS }, (_, index) => tab(String(index + 1)))
    const updated = upsertClinicalWorkspaceTab(initial, tab('9'))

    expect(updated).toHaveLength(MAX_CLINICAL_WORKSPACE_TABS)
    expect(updated[0].encounterId).toBe('9')
    expect(updated.some((item) => item.encounterId === '8')).toBe(false)
  })

  it('replaces an existing tab instead of duplicating it', () => {
    const updated = upsertClinicalWorkspaceTab([tab('1'), tab('2')], {
      ...tab('2'),
      patientName: 'Paciente Atualizado',
    })

    expect(updated).toHaveLength(2)
    expect(updated[0]).toMatchObject({
      encounterId: '2',
      patientName: 'Paciente Atualizado',
    })
  })

  it('removes a closed encounter tab', () => {
    expect(removeClinicalWorkspaceTab([tab('1'), tab('2')], '1')).toEqual([tab('2')])
  })
})
