import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SusProducaoPanel from './SusProducaoPanel'
import type { SusCompetencia } from './sus-types'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: any
    constructor(status: number, body: any) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

// Import the mocked ApiError so tests can construct rejections.
import { ApiError } from '@/lib/api'

const COMP_ABERTA: SusCompetencia = {
  id: 7,
  establishment: 'f1',
  competencia: '2026-07',
  status: 'aberta',
}
const COMP_FECHADA: SusCompetencia = { ...COMP_ABERTA, status: 'fechada' }

function renderPanel(comp: SusCompetencia, extra: Partial<Parameters<typeof SusProducaoPanel>[0]> = {}) {
  const onChanged = vi.fn()
  render(
    <SusProducaoPanel
      competencia={comp}
      bpaICount={2}
      bpaCCount={1}
      apacCount={3}
      totalValor={125}
      canWrite
      canExport
      onChanged={onChanged}
      {...extra}
    />,
  )
  return onChanged
}

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>
let clickSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  createObjectURL = vi.fn(() => 'blob:fake')
  revokeObjectURL = vi.fn()
  // jsdom lacks URL.createObjectURL — stub the Blob-download plumbing.
  ;(URL as any).createObjectURL = createObjectURL
  ;(URL as any).revokeObjectURL = revokeObjectURL
  clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  clickSpy.mockRestore()
})

describe('SusProducaoPanel', () => {
  it('renders KPIs (counts + total valor)', () => {
    renderPanel(COMP_ABERTA)
    expect(screen.getByText('BPA-I (gerado)')).toBeInTheDocument()
    expect(screen.getByText('APAC')).toBeInTheDocument()
    expect(screen.getByText(/125,00/)).toBeInTheDocument()
  })

  it('gera produção and shows the result', async () => {
    mockApiFetch.mockResolvedValue({ bpa_i_count: 3, total_valor: '150.00' })
    const onChanged = renderPanel(COMP_ABERTA)
    fireEvent.click(screen.getByRole('button', { name: /Gerar produção/ }))
    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) =>
          url === '/api/v1/billing/sus-competencias/7/gerar-producao/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    expect(await screen.findByText(/3 BPA-I/)).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it('handles a 409 on gerar produção (competência fechada)', async () => {
    mockApiFetch.mockRejectedValue(new ApiError(409, { detail: 'Competência fechada.' }))
    const onChanged = renderPanel(COMP_ABERTA)
    fireEvent.click(screen.getByRole('button', { name: /Gerar produção/ }))
    expect(await screen.findByText('Competência fechada.')).toBeInTheDocument()
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('fecha a competência', async () => {
    mockApiFetch.mockResolvedValue({ ...COMP_ABERTA, status: 'fechada' })
    const onChanged = renderPanel(COMP_ABERTA)
    fireEvent.click(screen.getByRole('button', { name: /Fechar competência/ }))
    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) =>
          url === '/api/v1/billing/sus-competencias/7/fechar/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    expect(onChanged).toHaveBeenCalled()
  })

  it('exporta a remessa and downloads both .txt files (status fechada)', async () => {
    mockApiFetch.mockResolvedValue({
      remessa_bpa: 'BPA-CONTENT',
      remessa_apac: 'APAC-CONTENT',
      filename_bpa: 'PA202607.txt',
      filename_apac: 'AP202607.txt',
    })
    const onChanged = renderPanel(COMP_FECHADA)
    fireEvent.click(screen.getByRole('button', { name: /Exportar remessa/ }))
    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) =>
          url === '/api/v1/billing/sus-competencias/7/exportar/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    // Two Blob downloads (BPA + APAC).
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(2))
    expect(clickSpy).toHaveBeenCalledTimes(2)
    expect(onChanged).toHaveBeenCalled()
  })

  it('handles a 409 on exportar (não fechada)', async () => {
    mockApiFetch.mockRejectedValue(
      new ApiError(409, { detail: 'Feche a competência antes de exportar.' }),
    )
    renderPanel(COMP_FECHADA)
    fireEvent.click(screen.getByRole('button', { name: /Exportar remessa/ }))
    expect(
      await screen.findByText('Feche a competência antes de exportar.'),
    ).toBeInTheDocument()
    expect(clickSpy).not.toHaveBeenCalled()
  })

  it('hides gerar/fechar without sus.write', () => {
    renderPanel(COMP_ABERTA, { canWrite: false })
    expect(screen.queryByRole('button', { name: /Gerar produção/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Fechar competência/ })).not.toBeInTheDocument()
  })

  it('hides exportar without sus.export', () => {
    renderPanel(COMP_FECHADA, { canExport: false })
    expect(screen.queryByRole('button', { name: /Exportar remessa/ })).not.toBeInTheDocument()
  })

  it('disables exportar while the competência is not fechada', () => {
    renderPanel(COMP_ABERTA)
    expect(screen.getByRole('button', { name: /Exportar remessa/ })).toBeDisabled()
  })
})
