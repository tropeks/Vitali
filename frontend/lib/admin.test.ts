import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

describe('admin API helpers', () => {
  it('normalizes paginated and plain lists', () => {
    expect(listResults([1, 2])).toEqual([1, 2])
    expect(listResults({ results: [3] })).toEqual([3])
  })

  it('extracts actionable DRF validation errors', () => {
    const error = new ApiError(400, { code: ['Código já cadastrado.'] })
    expect(apiErrorMessage(error, 'fallback')).toBe('Código já cadastrado.')
  })
})
