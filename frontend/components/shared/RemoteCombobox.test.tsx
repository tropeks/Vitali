import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RemoteCombobox from './RemoteCombobox'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => mockApiFetch(...args) }))

type Option = { id: string; name: string }

function Subject({ onChange = vi.fn() }: { onChange?: (value: Option | null) => void }) {
  return (
    <RemoteCombobox<Option>
      label="Fornecedor"
      endpoint="/api/v1/pharmacy/suppliers/"
      value={null}
      getKey={item => item.id}
      getLabel={item => item.name}
      onChange={onChange}
    />
  )
}

describe('RemoteCombobox', () => {
  beforeEach(() => mockApiFetch.mockReset())

  it('debounces remote search and selects a result accessibly', async () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    mockApiFetch.mockResolvedValue({ results: [{ id: '1', name: 'Fornecedor Alfa' }], next: null })
    render(<Subject onChange={onChange} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'Fornecedor' }), { target: { value: 'Alfa' } })
    await vi.advanceTimersByTimeAsync(300)
    await vi.runAllTimersAsync()

    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/pharmacy/suppliers/?search=Alfa&page_size=20')
    fireEvent.click(screen.getByRole('option', { name: 'Fornecedor Alfa' }))
    expect(onChange).toHaveBeenCalledWith({ id: '1', name: 'Fornecedor Alfa' })
    vi.useRealTimers()
  })

  it('loads the next server page on demand', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ results: [{ id: '1', name: 'A' }], next: '/api/v1/pharmacy/suppliers/?page=2' })
      .mockResolvedValueOnce({ results: [{ id: '2', name: 'B' }], next: null })
    render(<Subject />)

    fireEvent.focus(screen.getByRole('combobox', { name: 'Fornecedor' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Carregar mais' }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenLastCalledWith('/api/v1/pharmacy/suppliers/?page=2'))
    expect(await screen.findByRole('option', { name: 'B' })).toBeInTheDocument()
  })
})
