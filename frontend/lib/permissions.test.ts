import { describe, expect, it } from 'vitest'
import { PERMISSIONS, ALL_PERMISSIONS, canSee, type NavGate } from './permissions'
import type { UserDTO } from './auth'

const baseUser: Pick<UserDTO, 'permissions' | 'is_superuser'> = {
  permissions: ['emr.read', 'organization.read'],
  is_superuser: false,
}

describe('permission catalog', () => {
  it('exposes canonical backend strings as consts', () => {
    expect(PERMISSIONS.EMR_READ).toBe('emr.read')
    expect(PERMISSIONS.ORGANIZATION_READ).toBe('organization.read')
    expect(PERMISSIONS.HR_MANAGE).toBe('hr.manage')
    expect(PERMISSIONS.BILLING_FULL).toBe('billing.full')
  })

  it('ALL_PERMISSIONS contains every catalog value', () => {
    expect(ALL_PERMISSIONS).toContain('emr.read')
    expect(ALL_PERMISSIONS).toContain('mpi.read')
    // no accidental duplicates
    expect(new Set(ALL_PERMISSIONS).size).toBe(ALL_PERMISSIONS.length)
  })
})

describe('canSee — module gate (gate 1)', () => {
  it('fail-open while modules load (null) so items do not flicker', () => {
    const gate: NavGate = { module: 'imaging', permissions: ['imaging.read'] }
    // permission missing here, so still hidden — but module gate itself passes on null
    expect(canSee({ permissions: ['imaging.read'], is_superuser: false }, gate, null)).toBe(true)
  })

  it('hides a module-gated item when the tenant lacks the module', () => {
    const gate: NavGate = { module: 'diagnostic_concession' }
    expect(canSee(baseUser, gate, ['emr', 'billing'])).toBe(false)
  })

  it('shows a module-gated item when the module is active', () => {
    const gate: NavGate = { module: 'imaging', permissions: ['imaging.read'] }
    expect(
      canSee({ permissions: ['imaging.read'], is_superuser: false }, gate, ['emr', 'imaging']),
    ).toBe(true)
  })
})

describe('canSee — RBAC permission gate (gate 2) NEVER fail-open', () => {
  it('hides the item when the user lacks every listed permission', () => {
    const gate: NavGate = { permissions: ['billing.read'] }
    expect(canSee(baseUser, gate, [])).toBe(false)
  })

  it('shows the item when the user holds at least one listed permission (.some)', () => {
    const gate: NavGate = { permissions: ['billing.read', 'organization.read'] }
    expect(canSee(baseUser, gate, [])).toBe(true)
  })

  it('hides the item when the user has no permissions array at all', () => {
    const gate: NavGate = { permissions: ['emr.read'] }
    expect(canSee({ is_superuser: false }, gate, null)).toBe(false)
  })

  it('an item with no permissions is not blocked by the RBAC gate', () => {
    expect(canSee({ permissions: [], is_superuser: false }, {}, null)).toBe(true)
  })
})

describe('canSee — superuser gate (gate 3, Plataforma)', () => {
  it('hides a superuser item for a non-superuser', () => {
    expect(canSee(baseUser, { superuser: true }, null)).toBe(false)
  })

  it('hides a superuser item when is_superuser is undefined (fail-safe default)', () => {
    expect(canSee({ permissions: [] }, { superuser: true }, null)).toBe(false)
  })

  it('shows a superuser item for a superuser', () => {
    expect(canSee({ permissions: [], is_superuser: true }, { superuser: true }, null)).toBe(true)
  })
})
