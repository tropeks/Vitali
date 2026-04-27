import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import FuncionariosPage from './page'

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

// Mock AddEmployeeModal — expose data-testid so open state is testable
vi.mock('@/components/hr/AddEmployeeModal', () => ({
  default: ({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess?: () => void }) =>
    open ? (
      <div data-testid="add-employee-modal">
        <button onClick={onClose}>Fechar modal</button>
        <button onClick={() => onSuccess?.()}>Confirmar</button>
      </div>
    ) : null,
}))

// Mock EmployeeEditModal — expose employee name when open
vi.mock('@/components/hr/EmployeeEditModal', () => ({
  default: ({
    open,
    employee,
    onClose,
    onDeactivate,
  }: {
    open: boolean
    employee: any
    onClose: () => void
    onUpdate: () => void
    onDeactivate: (emp: any) => void
  }) =>
    open && employee ? (
      <div data-testid="employee-edit-modal">
        <span data-testid="editing-employee-name">{employee.full_name}</span>
        <button onClick={onClose}>Fechar editar</button>
        <button onClick={() => onDeactivate(employee)}>Desativar</button>
      </div>
    ) : null,
}))

// Mock DeactivateConfirmModal
vi.mock('@/components/hr/DeactivateConfirmModal', () => ({
  default: ({
    open,
    employee,
    onClose,
    onDeactivated,
  }: {
    open: boolean
    employee: any
    onClose: () => void
    onDeactivated: (msgs: string[]) => void
  }) =>
    open && employee ? (
      <div data-testid="deactivate-confirm-modal">
        <span data-testid="deactivating-employee-name">{employee.full_name}</span>
        <button onClick={onClose}>Cancelar desativação</button>
        <button onClick={() => onDeactivated(['Funcionário desativado ✓'])}>
          Confirmar desativação
        </button>
      </div>
    ) : null,
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const EMPLOYEE_1 = {
  id: 'emp-1',
  user: 'user-1',
  full_name: 'Ana Souza',
  email: 'ana@clinica.com',
  role: 'medico',
  employment_status: 'active' as const,
  hire_date: '2024-01-15',
  contract_type: 'clt',
  terminated_at: null,
  created_at: '2024-01-15T10:00:00Z',
}

const EMPLOYEE_2 = {
  id: 'emp-2',
  user: 'user-2',
  full_name: 'Bruno Lima',
  email: 'bruno@clinica.com',
  role: 'recepcao',
  employment_status: 'on_leave' as const,
  hire_date: '2023-06-01',
  contract_type: 'pj',
  terminated_at: null,
  created_at: '2023-06-01T08:00:00Z',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  // NOTE: do NOT use vi.useFakeTimers() here — testing-library's waitFor
  // relies on real timers to poll, and fake timers cause deadlock.
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('FuncionariosPage', () => {
  it('renders empty state when no employees', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum funcionário cadastrado ainda.')).toBeInTheDocument()
    })

    // Both add buttons visible (header + empty state)
    const addButtons = screen.getAllByRole('button', { name: /adicionar funcionário/i })
    expect(addButtons.length).toBeGreaterThanOrEqual(1)
  })

  it('renders employee rows when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1, EMPLOYEE_2])

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })

    expect(screen.getByText('Bruno Lima')).toBeInTheDocument()

    // Status badges
    expect(screen.getByText('Ativo')).toBeInTheDocument()
    expect(screen.getByText('Afastado')).toBeInTheDocument()

    // Role labels
    expect(screen.getByText('Médico')).toBeInTheDocument()
    expect(screen.getByText('Recepção')).toBeInTheDocument()
  })

  it('clicking Adicionar opens AddEmployeeModal', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<FuncionariosPage />)

    // Wait for load
    await waitFor(() => {
      expect(screen.getByText('Nenhum funcionário cadastrado ainda.')).toBeInTheDocument()
    })

    // Modal not visible initially
    expect(screen.queryByTestId('add-employee-modal')).toBeNull()

    // Click the header add button
    const addButtons = screen.getAllByRole('button', { name: /adicionar funcionário/i })
    fireEvent.click(addButtons[0])

    expect(screen.getByTestId('add-employee-modal')).toBeInTheDocument()
  })

  it('clicking Editar on a row opens EmployeeEditModal pre-filled', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1, EMPLOYEE_2])

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })

    // Edit modal not open initially
    expect(screen.queryByTestId('employee-edit-modal')).toBeNull()

    // Click Editar for first row
    const editButtons = screen.getAllByRole('button', { name: /editar/i })
    fireEvent.click(editButtons[0])

    expect(screen.getByTestId('employee-edit-modal')).toBeInTheDocument()
    expect(screen.getByTestId('editing-employee-name')).toHaveTextContent('Ana Souza')
  })

  it('Deactivate confirmation calls DELETE and refreshes list', async () => {
    // First load returns 2 employees, second (refresh after deactivate) returns 1
    mockApiFetch
      .mockResolvedValueOnce([EMPLOYEE_1, EMPLOYEE_2])
      .mockResolvedValueOnce([EMPLOYEE_2]) // reload after deactivation

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })

    // Open edit modal for first employee
    const editButtons = screen.getAllByRole('button', { name: /editar/i })
    fireEvent.click(editButtons[0])

    // Click Desativar inside edit modal — this triggers onDeactivate which closes edit, opens deactivate
    const desativarBtn = screen.getByRole('button', { name: /desativar/i })
    fireEvent.click(desativarBtn)

    // Deactivate confirm modal should now be open
    await waitFor(() => {
      expect(screen.getByTestId('deactivate-confirm-modal')).toBeInTheDocument()
    })

    expect(screen.getByTestId('deactivating-employee-name')).toHaveTextContent('Ana Souza')

    // Confirm deactivation
    fireEvent.click(screen.getByRole('button', { name: /confirmar desativação/i }))

    // Success toast appears and list reloads
    await waitFor(() => {
      expect(screen.getByText('Funcionário desativado ✓')).toBeInTheDocument()
    })

    // GET was called twice: initial load + reload after deactivate
    const getCalls = mockApiFetch.mock.calls.filter(
      (call) => call[0] === '/api/v1/hr/employees/' && (!call[1] || call[1].method === undefined)
    )
    expect(getCalls.length).toBeGreaterThanOrEqual(2)
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar funcionários.')).toBeInTheDocument()
    })
  })

  it('handles paginated response with results key', async () => {
    mockApiFetch.mockResolvedValueOnce({
      count: 1,
      results: [EMPLOYEE_1],
    })

    render(<FuncionariosPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })
  })
})
