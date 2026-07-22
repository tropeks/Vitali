import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PatientAutocomplete from './PatientAutocomplete'
import { apiFetch } from '@/lib/api'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

const mockApiFetch = vi.mocked(apiFetch)

describe('PatientAutocomplete', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('busca remotamente com debounce e seleciona por teclado', async () => {
    const onChange = vi.fn()
    mockApiFetch.mockResolvedValue({
      results: [{ id: 'p-1', full_name: 'Maria Souza', medical_record_number: 'PAC-001' }],
      next: null,
    })
    render(<PatientAutocomplete value={null} onChange={onChange} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Paciente' }), { target: { value: 'Maria' } })
    expect(mockApiFetch).not.toHaveBeenCalled()
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining('search=Maria')))
    await screen.findByRole('option', { name: /Maria Souza/ })
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' })
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p-1' }))
  })

  it('pagina resultados sem duplicar pacientes', async () => {
    const user = userEvent.setup()
    mockApiFetch
      .mockResolvedValueOnce({
        results: [{ id: 'p-1', full_name: 'Ana Um' }],
        next: 'https://vitali.test/api/v1/patients/?search=Ana&page=2',
      })
      .mockResolvedValueOnce({
        results: [{ id: 'p-1', full_name: 'Ana Um' }, { id: 'p-2', full_name: 'Ana Dois' }],
        next: null,
      })
    render(<PatientAutocomplete value={null} onChange={vi.fn()} />)

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Ana' } })
    await screen.findByRole('option', { name: 'Ana Um' })
    await user.click(screen.getByRole('button', { name: 'Carregar mais pacientes' }))

    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2))
    expect(mockApiFetch).toHaveBeenLastCalledWith('/api/v1/patients/?search=Ana&page=2')
  })
})
