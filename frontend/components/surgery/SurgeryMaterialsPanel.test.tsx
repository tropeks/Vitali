import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiError } from '@/lib/api'
import SurgeryMaterialsPanel from './SurgeryMaterialsPanel'

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

const MATERIALS = [
  {
    id: 'mat-1',
    case: 'case-1',
    kind: 'opme',
    stock_item: null,
    description: 'Placa de titânio',
    quantity_planned: 2,
    quantity_consumed: 1,
    laterality: 'esquerda',
    lot: 'LOTE-42',
    serial: 'SN-9',
    manufacturer: 'Acme',
  },
  {
    id: 'mat-2',
    case: 'case-1',
    kind: 'medicamento',
    stock_item: null,
    description: 'Cefazolina 1g',
    quantity_planned: 3,
    quantity_consumed: 0,
    laterality: '',
    lot: '',
    serial: '',
    manufacturer: '',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SurgeryMaterialsPanel', () => {
  it('lists the case materials with planejado × consumido and OPME lot (read)', async () => {
    mockApiFetch.mockResolvedValue({ count: 2, results: MATERIALS })
    render(<SurgeryMaterialsPanel caseId="case-1" canManage={false} />)

    await waitFor(() => {
      expect(screen.getByText('Placa de titânio')).toBeInTheDocument()
    })
    // Fetch is scoped to the case.
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/surgical-materials/?case=case-1')
    // Kind labels.
    expect(screen.getByText('OPME')).toBeInTheDocument()
    expect(screen.getByText('Medicamento')).toBeInTheDocument()
    // Planejado × consumido.
    expect(screen.getByText(/1\s*\/\s*2/)).toBeInTheDocument()
    expect(screen.getByText(/0\s*\/\s*3/)).toBeInTheDocument()
    // OPME rastreabilidade.
    expect(screen.getByText(/LOTE-42/)).toBeInTheDocument()
    expect(screen.getByText(/SN-9/)).toBeInTheDocument()
  })

  it('shows the list with surgery.read but hides every write control without surgery.manage', async () => {
    mockApiFetch.mockResolvedValue({ results: MATERIALS })
    render(<SurgeryMaterialsPanel caseId="case-1" canManage={false} />)

    await waitFor(() => {
      expect(screen.getByText('Placa de titânio')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Adicionar material/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Registrar consumo/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remover/ })).not.toBeInTheDocument()
  })

  it('adds a material/OPME (POST with case/kind/description/quantity/lot)', async () => {
    let list: any[] = []
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-materials/' && opts?.method === 'POST') {
        list = [
          {
            id: 'mat-new',
            case: 'case-1',
            kind: 'opme',
            description: 'Parafuso',
            quantity_planned: 4,
            quantity_consumed: 0,
            lot: 'L-7',
          },
        ]
        return Promise.resolve({ id: 'mat-new' })
      }
      if (url.startsWith('/api/v1/surgical-materials/?case=')) {
        return Promise.resolve({ results: list })
      }
      return Promise.resolve({ results: [] })
    })

    render(<SurgeryMaterialsPanel caseId="case-1" canManage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Adicionar material/ })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Tipo'), { target: { value: 'opme' } })
    fireEvent.change(screen.getByLabelText('Descrição'), { target: { value: 'Parafuso' } })
    fireEvent.change(screen.getByLabelText('Quantidade planejada'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Lote (OPME)'), { target: { value: 'L-7' } })

    fireEvent.click(screen.getByRole('button', { name: /Adicionar material/ }))

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-materials/' && o?.method === 'POST',
      )
      expect(post).toBeTruthy()
      const body = JSON.parse(post![1].body)
      expect(body.case).toBe('case-1')
      expect(body.kind).toBe('opme')
      expect(body.description).toBe('Parafuso')
      expect(body.quantity_planned).toBe(4)
      expect(body.lot).toBe('L-7')
    })
    await waitFor(() => {
      expect(screen.getByText('Parafuso')).toBeInTheDocument()
    })
  })

  it('registers consumption and reflects the new consumed quantity', async () => {
    let list: any[] = [
      {
        id: 'mat-1',
        case: 'case-1',
        kind: 'material',
        description: 'Compressa',
        quantity_planned: 5,
        quantity_consumed: 1,
      },
    ]
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-materials/mat-1/consume/' && opts?.method === 'POST') {
        list = [{ ...list[0], quantity_consumed: 3 }]
        return Promise.resolve({ ...list[0] })
      }
      if (url.startsWith('/api/v1/surgical-materials/?case=')) {
        return Promise.resolve({ results: list })
      }
      return Promise.resolve({ results: [] })
    })

    render(<SurgeryMaterialsPanel caseId="case-1" canManage />)
    await waitFor(() => {
      expect(screen.getByText('Compressa')).toBeInTheDocument()
    })
    expect(screen.getByText(/1\s*\/\s*5/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Consumo de Compressa'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /Registrar consumo/ }))

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-materials/mat-1/consume/' && o?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(post![1].body).quantity).toBe(2)
    })
    await waitFor(() => {
      expect(screen.getByText(/3\s*\/\s*5/)).toBeInTheDocument()
    })
  })

  it('surfaces an invalid consume quantity (400) as a friendly message', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-materials/mat-1/consume/' && opts?.method === 'POST') {
        return Promise.reject(new ApiError(400, { detail: 'invalid' }))
      }
      if (url.startsWith('/api/v1/surgical-materials/?case=')) {
        return Promise.resolve({
          results: [
            {
              id: 'mat-1',
              case: 'case-1',
              kind: 'material',
              description: 'Compressa',
              quantity_planned: 5,
              quantity_consumed: 1,
            },
          ],
        })
      }
      return Promise.resolve({ results: [] })
    })

    render(<SurgeryMaterialsPanel caseId="case-1" canManage />)
    await waitFor(() => {
      expect(screen.getByText('Compressa')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Consumo de Compressa'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: /Registrar consumo/ }))

    await waitFor(() => {
      expect(screen.getByText(/quantidade inválida/i)).toBeInTheDocument()
    })
  })

  it('removes a material (DELETE) and reloads', async () => {
    let list: any[] = [
      {
        id: 'mat-1',
        case: 'case-1',
        kind: 'outro',
        description: 'Fio de sutura',
        quantity_planned: 1,
        quantity_consumed: 0,
      },
    ]
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-materials/mat-1/' && opts?.method === 'DELETE') {
        list = []
        return Promise.resolve({})
      }
      if (url.startsWith('/api/v1/surgical-materials/?case=')) {
        return Promise.resolve({ results: list })
      }
      return Promise.resolve({ results: [] })
    })

    render(<SurgeryMaterialsPanel caseId="case-1" canManage />)
    await waitFor(() => {
      expect(screen.getByText('Fio de sutura')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Remover Fio de sutura/ }))

    await waitFor(() => {
      const del = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-materials/mat-1/' && o?.method === 'DELETE',
      )
      expect(del).toBeTruthy()
    })
    await waitFor(() => {
      expect(screen.queryByText('Fio de sutura')).not.toBeInTheDocument()
    })
    confirmSpy.mockRestore()
  })

  it('shows an empty state when the case has no materials', async () => {
    mockApiFetch.mockResolvedValue({ results: [] })
    render(<SurgeryMaterialsPanel caseId="case-1" canManage={false} />)
    await waitFor(() => {
      expect(screen.getByText(/Nenhum material/i)).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<SurgeryMaterialsPanel caseId="case-1" canManage />)
    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar materiais/i)).toBeInTheDocument()
    })
  })
})
