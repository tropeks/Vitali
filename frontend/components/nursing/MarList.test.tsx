import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MarList from './MarList'
import type { MarDueItem } from './mar-types'

const ITEM_1: MarDueItem = {
  id: 'item-1',
  prescription: 'rx-1',
  drug_name: 'Dipirona',
  dose_amount: '500.0000',
  dose_unit: 'mg',
  route: 'oral',
  frequency_per_day: 4,
  dosage_instructions: '1 comprimido de 6/6h',
}

const ITEM_2: MarDueItem = {
  id: 'item-2',
  prescription: 'rx-1',
  drug_name: 'Amoxicilina',
  dose_amount: '875.0000',
  dose_unit: 'mg',
  route: 'oral',
  frequency_per_day: 2,
  dosage_instructions: null,
}

describe('MarList', () => {
  it('renders each due medication with drug name and dose', () => {
    render(<MarList items={[ITEM_1, ITEM_2]} administeredIds={[]} onCheck={vi.fn()} />)
    expect(screen.getByText('Dipirona')).toBeInTheDocument()
    expect(screen.getByText('Amoxicilina')).toBeInTheDocument()
    // dose formatted without trailing zeros noise
    expect(screen.getByText(/500\s*mg/)).toBeInTheDocument()
    expect(screen.getByText(/875\s*mg/)).toBeInTheDocument()
  })

  it('shows a Checar button for un-administered items and calls onCheck', () => {
    const onCheck = vi.fn()
    render(<MarList items={[ITEM_1]} administeredIds={[]} onCheck={onCheck} />)
    const btn = screen.getByRole('button', { name: 'Checar' })
    fireEvent.click(btn)
    expect(onCheck).toHaveBeenCalledWith(ITEM_1)
  })

  it('shows an "Administrado" badge and no Checar button once administered', () => {
    render(<MarList items={[ITEM_1]} administeredIds={['item-1']} onCheck={vi.fn()} />)
    expect(screen.getByText('Administrado')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Checar' })).not.toBeInTheDocument()
  })
})
