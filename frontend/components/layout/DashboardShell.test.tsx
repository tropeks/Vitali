import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import DashboardShell from './DashboardShell'
import type { UserDTO } from '@/lib/auth'

const push = vi.fn()
let pathname = '/dashboard'

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, refresh: vi.fn() }),
}))

vi.mock('@/hooks/useHasModule', () => ({
  useActiveModules: () => ['emr', 'billing', 'pharmacy', 'rh'],
}))

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}))

vi.mock('@/components/shared/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}))

const user: UserDTO = {
  id: 'u-1',
  full_name: 'E2E Admin',
  email: 'admin@test.com',
  role_name: 'admin',
  permissions: ['organization.read'],
  active_modules: ['emr', 'billing', 'pharmacy', 'rh'],
}

beforeEach(() => {
  pathname = '/dashboard'
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

  it('shows administration only when the session carries an eligible permission', () => {
    const { rerender } = render(<DashboardShell user={user}><div /></DashboardShell>)
    expect(screen.getByRole('link', { name: /Administração/ })).toBeInTheDocument()

    rerender(<DashboardShell user={{ ...user, permissions: [] }}><div /></DashboardShell>)
    expect(screen.queryByRole('link', { name: /Administração/ })).not.toBeInTheDocument()
  })
})
