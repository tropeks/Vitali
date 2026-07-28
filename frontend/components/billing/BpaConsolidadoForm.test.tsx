import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import BpaConsolidadoForm from './BpaConsolidadoForm'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

// SIGTAP search returns the INTEGER pk in `id`; the CBO mock also returns an
// `id` so the payload assertion can verify the FK pk is sent (see the sus-types
// caveat about the real CBO endpoint not emitting it today).
function routeApi(overrides: { postBpaC?: () => any } = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url === '/api/v1/billing/bpa-consolidado/' && opts?.method === 'POST') {
      return Promise.resolve(overrides.postBpaC ? overrides.postBpaC() : { id: 1 })
    }
    if (url.startsWith('/api/v1/sigtap/')) {
      return Promise.resolve([{ id: 10, code: '0301010010', display: 'Consulta médica' }])
    }
    if (url.startsWith('/api/v1/terminology/cbo/')) {
      return Promise.resolve([{ id: 5, code: '225125', display: 'Médico clínico' }])
    }
    return Promise.resolve([])
  })
}

async function pickCombobox(name: RegExp, optionText: RegExp) {
  const input = screen.getByRole('combobox', { name })
  fireEvent.focus(input)
  const option = await screen.findByRole('option', { name: optionText })
  fireEvent.click(option)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BpaConsolidadoForm', () => {
  it('adds a BPA-C line with the correct POST payload (sigtap + cbo pks)', async () => {
    routeApi()
    const onAdded = vi.fn()
    render(<BpaConsolidadoForm competenciaId={7} onAdded={onAdded} />)

    await pickCombobox(/Procedimento SIGTAP/, /0301010010/)
    await pickCombobox(/Ocupação CBO/, /225125/)
    fireEvent.change(screen.getByLabelText('Idade (faixa etária)'), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '2' } })

    fireEvent.click(screen.getByRole('button', { name: /Adicionar BPA-C/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) => url === '/api/v1/billing/bpa-consolidado/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/billing/bpa-consolidado/' && opts?.method === 'POST',
    )
    const body = JSON.parse(postCall![1].body)
    expect(body).toEqual({ competencia: 7, sigtap: 10, cbo: 5, idade: 30, quantidade: 2 })
    await waitFor(() => expect(onAdded).toHaveBeenCalled())
  })

  it('keeps the submit disabled until sigtap, cbo and idade are set', async () => {
    routeApi()
    render(<BpaConsolidadoForm competenciaId={7} onAdded={vi.fn()} />)
    const submit = screen.getByRole('button', { name: /Adicionar BPA-C/ })
    expect(submit).toBeDisabled()

    await pickCombobox(/Procedimento SIGTAP/, /0301010010/)
    await pickCombobox(/Ocupação CBO/, /225125/)
    // Still disabled without idade.
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Idade (faixa etária)'), { target: { value: '30' } })
    expect(submit).not.toBeDisabled()
  })
})
