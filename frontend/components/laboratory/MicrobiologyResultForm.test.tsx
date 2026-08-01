import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import MicrobiologyResultForm from './MicrobiologyResultForm'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number) {
      super(`API error ${status}`)
      this.status = status
    }
  },
}))

const mockApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MicrobiologyResultForm', () => {
  it('posts the nested culture + organism + antibiogram tree', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onCreated = vi.fn()
    render(<MicrobiologyResultForm orderItemId="oi1" onCreated={onCreated} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Resultado da cultura'), {
      target: { value: 'positiva' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Adicionar organismo/ }))
    fireEvent.change(screen.getByLabelText('Organismo 1'), {
      target: { value: 'Escherichia coli' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Antibiótico/ }))
    fireEvent.change(screen.getByLabelText('Antibiótico 1-1'), {
      target: { value: 'Ampicilina' },
    })
    fireEvent.change(screen.getByLabelText('Interpretação 1-1'), { target: { value: 'R' } })

    fireEvent.click(screen.getByRole('button', { name: 'Salvar resultado' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/microbiology-results/')
    const body = JSON.parse(opts!.body as string)
    expect(body.order_item).toBe('oi1')
    expect(body.culture_result).toBe('positiva')
    expect(body.organisms_input).toHaveLength(1)
    expect(body.organisms_input[0].organism_name).toBe('Escherichia coli')
    expect(body.organisms_input[0].antibiogram[0]).toEqual({
      antibiotic: 'Ampicilina',
      interpretation: 'R',
    })
  })

  it('drops blank organism rows from the payload', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    render(<MicrobiologyResultForm orderItemId="oi1" onCreated={vi.fn()} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /Adicionar organismo/ }))
    // leave organism name blank
    fireEvent.click(screen.getByRole('button', { name: 'Salvar resultado' }))
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const body = JSON.parse(mockApiFetch.mock.calls[0][1]!.body as string)
    expect(body.organisms_input).toHaveLength(0)
  })
})
