/**
 * Tests for /auth/change-password forced-flow page.
 *
 * NOTE: No test runner is configured in package.json (no vitest/jest).
 * These tests are written for Vitest + @testing-library/react.
 * Wire up the runner with:
 *   npm install -D vitest @vitejs/plugin-react @testing-library/react @testing-library/user-event jsdom
 * and add a vitest.config.ts before running.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChangePasswordPage from './page'

// Mock next/navigation
const mockPush = vi.fn()
const mockRefresh = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}))

// Mock getAccessToken
vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

// Mock global fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ChangePasswordPage', () => {
  it('render — form fields visible', () => {
    render(<ChangePasswordPage />)

    expect(screen.getByLabelText(/senha atual/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^nova senha/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/confirme a nova senha/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /alterar senha/i })).toBeInTheDocument()
  })

  it("validation — passwords don't match", async () => {
    render(<ChangePasswordPage />)

    await userEvent.type(screen.getByLabelText(/senha atual/i), 'oldpassword')
    await userEvent.type(screen.getByLabelText(/^nova senha/i), 'newpass123')
    await userEvent.type(screen.getByLabelText(/confirme a nova senha/i), 'different123')
    fireEvent.submit(screen.getByRole('button', { name: /alterar senha/i }).closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('As senhas não coincidem.')
    })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('validation — new password too short', async () => {
    render(<ChangePasswordPage />)

    await userEvent.type(screen.getByLabelText(/senha atual/i), 'oldpassword')
    await userEvent.type(screen.getByLabelText(/^nova senha/i), 'short')
    await userEvent.type(screen.getByLabelText(/confirme a nova senha/i), 'short')
    fireEvent.submit(screen.getByRole('button', { name: /alterar senha/i }).closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('no mínimo 8 caracteres')
    })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('validation — new equals current', async () => {
    render(<ChangePasswordPage />)

    await userEvent.type(screen.getByLabelText(/senha atual/i), 'samepassword1')
    await userEvent.type(screen.getByLabelText(/^nova senha/i), 'samepassword1')
    await userEvent.type(screen.getByLabelText(/confirme a nova senha/i), 'samepassword1')
    fireEvent.submit(screen.getByRole('button', { name: /alterar senha/i }).closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('diferente da atual')
    })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('submit success → redirect to /dashboard', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ detail: 'Senha alterada.' }) })

    render(<ChangePasswordPage />)

    await userEvent.type(screen.getByLabelText(/senha atual/i), 'oldpassword')
    await userEvent.type(screen.getByLabelText(/^nova senha/i), 'newpassword123')
    await userEvent.type(screen.getByLabelText(/confirme a nova senha/i), 'newpassword123')
    fireEvent.submit(screen.getByRole('button', { name: /alterar senha/i }).closest('form')!)

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/dashboard')
    })
    expect(mockRefresh).toHaveBeenCalled()
  })

  it('submit error from API — displays server error message', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: { message: 'Senha atual incorreta.' } }),
    })

    render(<ChangePasswordPage />)

    await userEvent.type(screen.getByLabelText(/senha atual/i), 'wrongpassword')
    await userEvent.type(screen.getByLabelText(/^nova senha/i), 'newpassword123')
    await userEvent.type(screen.getByLabelText(/confirme a nova senha/i), 'newpassword123')
    fireEvent.submit(screen.getByRole('button', { name: /alterar senha/i }).closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Senha atual incorreta.')
    })
    expect(mockPush).not.toHaveBeenCalled()
  })
})
