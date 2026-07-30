import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import ReconciliarAihModal from './ReconciliarAihModal'

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

describe('ReconciliarAihModal', () => {
  it('disables confirm until a 13-digit number is entered', () => {
    render(<ReconciliarAihModal aihId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={vi.fn()} />)
    const confirm = screen.getByRole('button', { name: 'Confirmar reconciliação' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Número oficial'), { target: { value: '9999999999999' } })
    expect(confirm).toBeEnabled()
  })

  it('posts the official number to the AIH endpoint', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onReconciled = vi.fn()
    render(
      <ReconciliarAihModal aihId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={onReconciled} />
    )
    fireEvent.change(screen.getByLabelText('Número oficial'), { target: { value: '9999999999999' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar reconciliação' }))

    await waitFor(() => expect(onReconciled).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/aih-autorizacoes/1/reconciliar/')
    expect(JSON.parse(opts!.body as string).numero_oficial).toBe('9999999999999')
  })

  it('surfaces a friendly message on 409', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'x' }))
    render(<ReconciliarAihModal aihId={1} numeroAtual="prov" onClose={vi.fn()} onReconciled={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Número oficial'), { target: { value: '9999999999999' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar reconciliação' }))
    await waitFor(() =>
      expect(screen.getByText(/inválido\/duplicado ou AIH já autorizada/i)).toBeInTheDocument()
    )
  })
})
