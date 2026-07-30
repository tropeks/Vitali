import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import ReconciliarApacModal from './ReconciliarApacModal'

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

const mockApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReconciliarApacModal', () => {
  it('disables confirm until a 13-digit number is entered', () => {
    render(
      <ReconciliarApacModal apacId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={vi.fn()} />
    )
    const confirm = screen.getByRole('button', { name: 'Confirmar reconciliação' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Número oficial'), { target: { value: '123' } })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Número oficial'), {
      target: { value: '9999999999999' },
    })
    expect(confirm).toBeEnabled()
  })

  it('posts the official number and optional date', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onReconciled = vi.fn()
    render(
      <ReconciliarApacModal apacId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={onReconciled} />
    )
    fireEvent.change(screen.getByLabelText('Número oficial'), {
      target: { value: '9999999999999' },
    })
    fireEvent.change(screen.getByLabelText('Data da autorização'), {
      target: { value: '2026-07-20' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar reconciliação' }))

    await waitFor(() => expect(onReconciled).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/apac-autorizacoes/1/reconciliar/')
    const body = JSON.parse(opts!.body as string)
    expect(body.numero_oficial).toBe('9999999999999')
    expect(body.data_autorizacao).toBe('2026-07-20')
  })

  it('surfaces a friendly message on 409', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'x' }))
    render(
      <ReconciliarApacModal apacId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={vi.fn()} />
    )
    fireEvent.change(screen.getByLabelText('Número oficial'), {
      target: { value: '9999999999999' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar reconciliação' }))
    await waitFor(() =>
      expect(screen.getByText(/inválido\/duplicado ou APAC já autorizada/i)).toBeInTheDocument()
    )
  })
})
