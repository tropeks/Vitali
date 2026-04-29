/**
 * Vitest + @testing-library/react tests for AddEmployeeModal (T8)
 *
 * Run: npx vitest run components/hr/AddEmployeeModal.test.tsx
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AddEmployeeModal from './AddEmployeeModal'

// ─── Mocks ────────────────────────────────────────────────────────────────────

// Mock apiFetch from lib/api
vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    body: any
    constructor(status: number, body: any, message?: string) {
      super(message ?? `API error ${status}`)
      this.status = status
      this.body = body
    }
  },
}))

// Mock getAccessToken (apiFetch imports it internally; the mock above bypasses it)
vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

// ─── Helpers ──────────────────────────────────────────────────────────────────

import { apiFetch } from '@/lib/api'
const mockApiFetch = vi.mocked(apiFetch)

// Default open props
const DEFAULT_PROPS = {
  open: true,
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

// Fill step 1 required fields
async function fillStep1(overrides: { full_name?: string; email?: string; cpf?: string } = {}) {
  await userEvent.type(
    screen.getByLabelText(/nome completo/i),
    overrides.full_name ?? 'Ana Lima'
  )
  await userEvent.type(
    screen.getByLabelText(/e-mail/i),
    overrides.email ?? 'ana@clinica.com.br'
  )
  // Type raw digits — CPF input applies mask
  await userEvent.type(
    screen.getByLabelText(/cpf/i),
    overrides.cpf ?? '12345678901'
  )
}

// Advance from step 1 to step 2
async function goToStep2() {
  await fillStep1()
  const next = screen.getByRole('button', { name: /próximo/i })
  expect(next).not.toBeDisabled()
  fireEvent.click(next)
  await waitFor(() => expect(screen.getByText(/etapa 2 de 3/i)).toBeInTheDocument())
}

// Advance from step 2 to step 3
async function goToStep3() {
  await goToStep2()
  const next = screen.getByRole('button', { name: /próximo/i })
  fireEvent.click(next)
  await waitFor(() => expect(screen.getByText(/etapa 3 de 3/i)).toBeInTheDocument())
}

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AddEmployeeModal', () => {
  // ── 1. Renders step 1 with personal fields ────────────────────────────────
  it('renders step 1 with personal fields when open', () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)

    expect(screen.getByLabelText(/nome completo/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/e-mail/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/cpf/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/telefone/i)).toBeInTheDocument()
    expect(screen.getByText(/etapa 1 de 3/i)).toBeInTheDocument()
  })

  // ── 2. Does not render when open is false ────────────────────────────────
  it('does not render when open is false', () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} open={false} />)
    expect(screen.queryByText(/novo funcionário/i)).not.toBeInTheDocument()
  })

  // ── 3. Step 2 conditionally shows council fields when role is medico ──────
  it('step 2 conditionally shows council fields when role is medico', async () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)
    await goToStep2()

    // Change role to medico
    const roleSelect = screen.getByLabelText(/função/i)
    await userEvent.selectOptions(roleSelect, 'medico')

    expect(screen.getByText(/conselho profissional/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/conselho \*/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/número/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/uf/i)).toBeInTheDocument()

    // Change to admin — council fields should disappear
    await userEvent.selectOptions(roleSelect, 'admin')
    expect(screen.queryByText(/conselho profissional/i)).not.toBeInTheDocument()
  })

  // ── 4. Step 2 blocks Próximo with clinical role and missing council ────────
  it('step 2 blocks Próximo with clinical role and missing council', async () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)
    await goToStep2()

    // Select a clinical role
    const roleSelect = screen.getByLabelText(/função/i)
    await userEvent.selectOptions(roleSelect, 'medico')

    // council fields are empty → Próximo should be disabled
    const next = screen.getByRole('button', { name: /próximo/i })
    expect(next).toBeDisabled()
  })

  // ── 5. Step 3 random password button generates 16-char string ────────────
  it('step 3 random password button generates 16-char string', async () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)
    await goToStep3()

    // Select random password mode
    const radioRandom = screen.getByDisplayValue('random_password')
    fireEvent.click(radioRandom)

    // Click Gerar
    const gerarBtn = screen.getByRole('button', { name: /gerar/i })
    fireEvent.click(gerarBtn)

    // The generated password should show in a readonly input
    await waitFor(() => {
      const passwordInput = screen.getByLabelText(/senha gerada/i) as HTMLInputElement
      expect(passwordInput.value).toHaveLength(16)
    })
  })

  // ── 6. Step 3 invite mode hides password field ───────────────────────────
  it('step 3 invite mode hides password field', async () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)
    await goToStep3()

    // Select invite mode
    const radioInvite = screen.getByDisplayValue('invite')
    fireEvent.click(radioInvite)

    // No text input for password should be visible
    expect(screen.queryByPlaceholderText(/senha temporária/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/senha gerada/i)).not.toBeInTheDocument()
  })

  // ── 7. WhatsApp checkbox disabled without phone ──────────────────────────
  it('whatsapp checkbox disabled without phone, enabled when phone filled', async () => {
    render(<AddEmployeeModal {...DEFAULT_PROPS} />)

    // Go through step 1 without phone, then to step 3
    await fillStep1()
    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 2 de 3/i))
    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 3 de 3/i))

    const whatsappCheckbox = screen.getByLabelText(/configurar whatsapp/i)
    expect(whatsappCheckbox).toBeDisabled()

    // Go back to step 1 and fill the phone, then forward again
    fireEvent.click(screen.getByRole('button', { name: /voltar/i }))
    await waitFor(() => screen.getByText(/etapa 2 de 3/i))
    fireEvent.click(screen.getByRole('button', { name: /voltar/i }))
    await waitFor(() => screen.getByText(/etapa 1 de 3/i))

    await userEvent.type(screen.getByLabelText(/telefone/i), '+5511999999999')

    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 2 de 3/i))
    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 3 de 3/i))

    const whatsappCheckbox2 = screen.getByLabelText(/configurar whatsapp/i)
    expect(whatsappCheckbox2).not.toBeDisabled()
  })

  // ── 8. Submit calls apiFetch with correct payload shape ──────────────────
  it('submit calls apiFetch with correct payload shape', async () => {
    mockApiFetch.mockResolvedValueOnce({
      employee_id: 'emp-1',
      user_id: 'usr-1',
      professional_id: null,
      whatsapp_setup_queued: false,
      correlation_id: 'corr-1',
    })

    render(<AddEmployeeModal {...DEFAULT_PROPS} />)

    // Step 1
    await userEvent.type(screen.getByLabelText(/nome completo/i), 'Carlos Souza')
    await userEvent.type(screen.getByLabelText(/e-mail/i), 'carlos@clinica.com.br')
    await userEvent.type(screen.getByLabelText(/cpf/i), '98765432100')
    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 2 de 3/i))

    // Step 2: keep defaults (recepcao, clt, active)
    fireEvent.click(screen.getByRole('button', { name: /próximo/i }))
    await waitFor(() => screen.getByText(/etapa 3 de 3/i))

    // Step 3: select typed_password and enter a password
    const radioTyped = screen.getByDisplayValue('typed_password')
    fireEvent.click(radioTyped)
    await userEvent.type(screen.getByPlaceholderText(/senha temporária/i), 'Temp@1234')

    const submitBtn = screen.getByRole('button', { name: /cadastrar funcionário/i })
    fireEvent.click(submitBtn)

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1))

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/employees/')
    expect(options?.method).toBe('POST')

    const body = JSON.parse(options?.body as string)
    expect(body).toMatchObject({
      full_name: 'Carlos Souza',
      email: 'carlos@clinica.com.br',
      cpf: '98765432100',
      role: 'recepcao',
      contract_type: 'clt',
      employment_status: 'active',
      auth_mode: 'typed_password',
      password: 'Temp@1234',
      setup_whatsapp: false,
    })
  })
})
