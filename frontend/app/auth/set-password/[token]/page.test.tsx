import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SetPasswordPage from './page'

// Mock next/navigation
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ token: 'fake-jwt-token' }),
}))

// Mock global fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('SetPasswordPage', () => {
  it('renders password and confirm inputs', () => {
    render(<SetPasswordPage />)

    expect(screen.getByLabelText(/nova senha/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/confirmar senha/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /defina sua senha/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /definir senha e entrar/i })).toBeInTheDocument()
  })

  it('submit blocked with passwords too short', async () => {
    render(<SetPasswordPage />)

    await userEvent.type(screen.getByLabelText(/nova senha/i), 'abc')
    await userEvent.type(screen.getByLabelText(/confirmar senha/i), 'abc')
    fireEvent.submit(
      screen.getByRole('button', { name: /definir senha e entrar/i }).closest('form')!,
    )

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('no mínimo 8 caracteres')
    })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('submit blocked with mismatched passwords', async () => {
    render(<SetPasswordPage />)

    await userEvent.type(screen.getByLabelText(/nova senha/i), 'senha12345')
    await userEvent.type(screen.getByLabelText(/confirmar senha/i), 'outrasenha45')
    fireEvent.submit(
      screen.getByRole('button', { name: /definir senha e entrar/i }).closest('form')!,
    )

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('As senhas não conferem')
    })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('successful submit stores tokens and redirects to /dashboard', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access: 'access-token-abc', refresh: 'refresh-token-xyz' }),
    })

    render(<SetPasswordPage />)

    await userEvent.type(screen.getByLabelText(/nova senha/i), 'minhasenha123')
    await userEvent.type(screen.getByLabelText(/confirmar senha/i), 'minhasenha123')
    fireEvent.submit(
      screen.getByRole('button', { name: /definir senha e entrar/i }).closest('form')!,
    )

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/dashboard')
    })
    expect(localStorage.getItem('access_token')).toBe('access-token-abc')
    expect(localStorage.getItem('refresh_token')).toBe('refresh-token-xyz')
  })

  it('expired token shows 410 message', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 410,
      json: async () => ({}),
    })

    render(<SetPasswordPage />)

    await userEvent.type(screen.getByLabelText(/nova senha/i), 'minhasenha123')
    await userEvent.type(screen.getByLabelText(/confirmar senha/i), 'minhasenha123')
    fireEvent.submit(
      screen.getByRole('button', { name: /definir senha e entrar/i }).closest('form')!,
    )

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('expirou')
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('consumed token shows correct message', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ error: 'INVITATION_ALREADY_CONSUMED' }),
    })

    render(<SetPasswordPage />)

    await userEvent.type(screen.getByLabelText(/nova senha/i), 'minhasenha123')
    await userEvent.type(screen.getByLabelText(/confirmar senha/i), 'minhasenha123')
    fireEvent.submit(
      screen.getByRole('button', { name: /definir senha e entrar/i }).closest('form')!,
    )

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('já foi usado')
    })
    expect(mockPush).not.toHaveBeenCalled()
  })
})
