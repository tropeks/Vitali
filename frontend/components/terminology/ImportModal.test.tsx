import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ImportModal from './ImportModal'

// ─── Mocks ────────────────────────────────────────────────────────────────────

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
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

beforeEach(() => {
  vi.clearAllMocks()
})

function makeCsvFile(name = 'cbo.csv') {
  return new File(['codigo;descricao\n2231-05;Medico clinico'], name, { type: 'text/csv' })
}

describe('ImportModal', () => {
  it('POSTs a FormData body with the selected file to the /import/ endpoint for the system', async () => {
    mockApiFetch.mockResolvedValueOnce({ status: 'ok', created: 10, updated: 2, row_count: 12 })
    const onImported = vi.fn()

    render(<ImportModal system="cbo" label="CBO" onClose={() => {}} onImported={onImported} />)

    const file = makeCsvFile()
    const input = screen.getByLabelText(/Arquivo CSV/i) as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })

    fireEvent.click(screen.getByRole('button', { name: 'Importar' }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalled()
    })

    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/platform/terminology/cbo/import/')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.body.get('file')).toBe(file)

    // Shows run counts after success.
    expect(await screen.findByText(/Importação concluída/)).toBeInTheDocument()
    expect(screen.getByText(/Criados: 10/)).toBeInTheDocument()
    expect(screen.getByText(/Atualizados: 2/)).toBeInTheDocument();
  })

  it('includes the optional version field in the FormData when provided', async () => {
    mockApiFetch.mockResolvedValueOnce({ status: 'ok', created: 1, updated: 0 })

    render(<ImportModal system="loinc" label="LOINC" onClose={() => {}} onImported={() => {}} />)

    fireEvent.change(screen.getByLabelText(/Arquivo CSV/i), { target: { files: [makeCsvFile('loinc.csv')] } })
    fireEvent.change(screen.getByLabelText(/Versão/i), { target: { value: '2.76' } })

    fireEvent.click(screen.getByRole('button', { name: 'Importar' }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [, init] = mockApiFetch.mock.calls[0]
    expect(init.body.get('version')).toBe('2.76')
  })

  it('shows a validation error and does not call the API when no file is selected', async () => {
    render(<ImportModal system="cbo" label="CBO" onClose={() => {}} onImported={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: 'Importar' }))

    expect(await screen.findByText(/Selecione um arquivo/)).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('shows an error message when the import request fails (e.g. 400 missing file / 403 non-superuser)', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Falha ao importar'))

    render(<ImportModal system="ucum" label="UCUM" onClose={() => {}} onImported={() => {}} />)

    fireEvent.change(screen.getByLabelText(/Arquivo CSV/i), { target: { files: [makeCsvFile('ucum.csv')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Importar' }))

    await waitFor(() => {
      expect(screen.getByText('Falha ao importar')).toBeInTheDocument()
    })
  })

  it('calls onClose when the close button is clicked', () => {
    const onClose = vi.fn()
    render(<ImportModal system="cbo" label="CBO" onClose={onClose} onImported={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalled()
  })
})
