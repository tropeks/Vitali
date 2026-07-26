import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import DashboardShell from './DashboardShell'
import type { UserDTO } from '@/lib/auth'

const push = vi.fn()
let pathname = '/dashboard'

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, refresh: vi.fn() }),
}))

const activeModulesMock = vi.hoisted(() => ({
  current: ['emr', 'billing', 'pharmacy', 'rh', 'imaging'] as string[] | null,
}))

vi.mock('@/hooks/useHasModule', () => ({
  useActiveModules: () => activeModulesMock.current,
}))

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}))

vi.mock('@/components/shared/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}))

// A representative admin session: carries the canonical clinical + back-office perms.
const ADMIN_PERMS = [
  'admin',
  'emr.read',
  'emr.write',
  'patients.read',
  'schedule.read',
  'billing.read',
  'billing.full',
  'imaging.read',
  'organization.read',
  'mpi.read',
  'workflow.read',
  'hr.manage',
  'pharmacy.read',
  'pharmacy.stock_manage',
]

const user: UserDTO = {
  id: 'u-1',
  full_name: 'E2E Admin',
  email: 'admin@test.com',
  role_name: 'admin',
  permissions: ADMIN_PERMS,
  active_modules: ['emr', 'billing', 'pharmacy', 'rh', 'imaging'],
  is_superuser: false,
}

beforeEach(() => {
  pathname = '/dashboard'
  activeModulesMock.current = ['emr', 'billing', 'pharmacy', 'rh', 'imaging']
  vi.clearAllMocks()
})

describe('DashboardShell', () => {
  it('renders global sidebar on operational pages', () => {
    render(
      <DashboardShell user={user}>
        <h1>Centro operacional</h1>
      </DashboardShell>,
    )

    expect(screen.getByRole('link', { name: /Pacientes/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Laboratório/ })).toHaveAttribute(
      'href',
      '/laboratorio',
    )
    expect(screen.getByRole('heading', { name: 'Centro operacional' })).toBeInTheDocument()
  })

  it('hides global sidebar in encounter clinical workspace', () => {
    pathname = '/encounters/enc-1'

    render(
      <DashboardShell user={user}>
        <h1>Paciente Teste</h1>
      </DashboardShell>,
    )

    expect(screen.queryByRole('link', { name: /Pacientes/ })).not.toBeInTheDocument()
    expect(screen.getByText('Atendimento')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Paciente Teste' })).toBeInTheDocument()
  })

  it('renders the domain group headers', () => {
    render(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.getByRole('button', { name: /Atendimento/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Financeiro/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Administração/ })).toBeInTheDocument()
  })

  it('collapses a group when its header is clicked', () => {
    render(<DashboardShell user={user}><div /></DashboardShell>)
    // Financeiro group is expanded by default → Faturamento link visible
    expect(screen.getByRole('link', { name: /Faturamento/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Financeiro/ }))
    expect(screen.queryByRole('link', { name: /Faturamento/ })).not.toBeInTheDocument()
  })

  it('hides an RBAC-gated item when the session lacks the permission and shows it when present', () => {
    const { rerender } = render(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.getByRole('link', { name: /Estrutura organizacional/ })).toBeInTheDocument()

    rerender(
      <DashboardShell user={{ ...user, permissions: ['emr.read'] }}>
        <div />
      </DashboardShell>,
    )
    expect(
      screen.queryByRole('link', { name: /Estrutura organizacional/ }),
    ).not.toBeInTheDocument()
  })

  it('RBAC permission gate never fail-opens (missing perm hides the item)', () => {
    // billing module active, but user lacks billing.* → Faturamento hidden
    render(
      <DashboardShell user={{ ...user, permissions: ['emr.read'] }}>
        <div />
      </DashboardShell>,
    )
    expect(screen.queryByRole('link', { name: /Faturamento/ })).not.toBeInTheDocument()
  })

  it('hides Concessão when the tenant module is inactive and shows it once active', () => {
    activeModulesMock.current = ['emr', 'billing', 'pharmacy', 'rh']
    const { rerender } = render(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.queryByRole('link', { name: /Concessão/ })).not.toBeInTheDocument()

    activeModulesMock.current = ['emr', 'billing', 'pharmacy', 'rh', 'diagnostic_concession']
    rerender(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.getByRole('link', { name: /Concessão/ })).toHaveAttribute('href', '/concessao')
  })

  it('hides the Plataforma group for a non-superuser', () => {
    render(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.queryByRole('button', { name: /Plataforma/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Tenants/ })).not.toBeInTheDocument()
  })

  it('shows the Plataforma group only for a superuser', () => {
    render(
      <DashboardShell user={{ ...user, is_superuser: true }}>
        <div />
      </DashboardShell>,
    )
    expect(screen.getByRole('button', { name: /Plataforma/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Tenants/ })).toHaveAttribute(
      'href',
      '/platform/tenants',
    )
  })
})
