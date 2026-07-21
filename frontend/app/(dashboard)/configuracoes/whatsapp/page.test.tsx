import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import WhatsAppSettingsPage from './page'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => mockApiFetch(...args) }))

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockResolvedValue({
    status: 'ok',
    evolution_api: { state: 'open', phone: '+5511999999999' },
  })
})

describe('WhatsAppSettingsPage authenticated API calls', () => {
  it('loads health and reconnects through apiFetch', async () => {
    render(<WhatsAppSettingsPage />)
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/whatsapp/health/')
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Reconectar' }))
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/whatsapp/setup-webhook/', {
        method: 'POST',
      })
    )
  })

  it('loads contacts through apiFetch', async () => {
    render(<WhatsAppSettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Conversas' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/whatsapp/contacts/')
    )
  })
})
