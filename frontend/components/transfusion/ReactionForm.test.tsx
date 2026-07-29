import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import ReactionForm from './ReactionForm'
import type { TransfusionAdministration } from './transfusion-types'

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

const ADMIN: TransfusionAdministration = {
  id: 'adm-1',
  request: 'req-1',
  patient: 'patient-1',
  bag_identifier: 'DIN-0001',
  status: 'concluida',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReactionForm', () => {
  it('POSTs the reação (tipo/gravidade/descrição/conduta/notificado) to the administração', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'rx-1', tipo: 'hemolitica_aguda' })
    const onSaved = vi.fn()
    render(<ReactionForm administration={ADMIN} onClose={vi.fn()} onSaved={onSaved} />)

    fireEvent.change(screen.getByLabelText('Tipo de reação'), {
      target: { value: 'hemolitica_aguda' },
    })
    fireEvent.change(screen.getByLabelText('Gravidade'), { target: { value: 'grave' } })
    fireEvent.change(screen.getByLabelText('Descrição'), {
      target: { value: 'Hemólise aguda com hemoglobinúria.' },
    })
    fireEvent.change(screen.getByLabelText('Conduta'), {
      target: { value: 'Interrompida a transfusão; suporte hemodinâmico.' },
    })
    fireEvent.click(screen.getByLabelText('Notificado à hemovigilância'))

    fireEvent.click(screen.getByRole('button', { name: 'Registrar reação' }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/transfusion-administrations/adm-1/reacao/')
    const body = JSON.parse((options as RequestInit)?.body as string)
    expect(body).toEqual({
      tipo: 'hemolitica_aguda',
      gravidade: 'grave',
      descricao: 'Hemólise aguda com hemoglobinúria.',
      conduta: 'Interrompida a transfusão; suporte hemodinâmico.',
      notificado_hemovigilancia: true,
    })
  })

  it('keeps the submit disabled until a descrição is filled', () => {
    render(<ReactionForm administration={ADMIN} onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Registrar reação' })).toBeDisabled()
  })
})
