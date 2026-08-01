import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import PathologyReportForm from './PathologyReportForm'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn((url: string) => {
    // RemoteCombobox GETs return an empty option page; the POST returns {}.
    if (url.startsWith('/api/v1/terminology/')) return Promise.resolve({ results: [] })
    return Promise.resolve({})
  }),
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

describe('PathologyReportForm', () => {
  it('posts the report + nested specimens', async () => {
    const onCreated = vi.fn()
    render(<PathologyReportForm orderItemId="oi2" onCreated={onCreated} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Situação do laudo'), { target: { value: 'final' } })
    fireEvent.click(screen.getByRole('button', { name: /Adicionar espécime/ }))
    fireEvent.change(screen.getByLabelText('Espécime 1 rótulo'), { target: { value: 'A' } })
    fireEvent.change(screen.getByLabelText('Espécime 1 sítio'), { target: { value: 'Mama' } })
    fireEvent.change(screen.getByLabelText('Espécime 1 blocos'), { target: { value: '3' } })

    fireEvent.click(screen.getByRole('button', { name: 'Salvar laudo' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/pathology-reports/' && (opts as any)?.method === 'POST',
    )
    expect(postCall).toBeTruthy()
    const body = JSON.parse((postCall![1] as any).body)
    expect(body.order_item).toBe('oi2')
    expect(body.status).toBe('final')
    expect(body.cid_o_topography_code).toBe('')
    expect(body.specimens_input).toEqual([{ label: 'A', site: 'Mama', blocks_count: 3 }])
  })
})
