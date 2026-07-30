import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import RejeitarAihModal from './RejeitarAihModal'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const mockApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('RejeitarAihModal', () => {
  it('disables confirm until a motivo is entered', () => {
    render(<RejeitarAihModal aihId={1} numeroAtual="2026" onClose={vi.fn()} onRejected={vi.fn()} />)
    const confirm = screen.getByRole('button', { name: 'Confirmar rejeição' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Motivo da rejeição'), {
      target: { value: 'Glosa' },
    })
    expect(confirm).toBeEnabled()
  })

  it('posts the motivo to the AIH endpoint', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onRejected = vi.fn()
    render(<RejeitarAihModal aihId={1} numeroAtual="2026" onClose={vi.fn()} onRejected={onRejected} />)
    fireEvent.change(screen.getByLabelText('Motivo da rejeição'), {
      target: { value: 'Glosa administrativa' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar rejeição' }))

    await waitFor(() => expect(onRejected).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/aih-autorizacoes/1/rejeitar/')
    expect(JSON.parse(opts!.body as string).motivo).toBe('Glosa administrativa')
  })
})
