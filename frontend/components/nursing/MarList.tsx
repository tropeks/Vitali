import { StatusBadge } from '@/components/shared'
import type { MarDueItem } from './mar-types'

const ADMINISTERED_META = {
  label: 'Administrado',
  badgeClass: 'border-green-200 bg-green-100 text-green-700',
}

/** "500.0000" + "mg" → "500 mg"; drops decimal noise, keeps real fractions. */
export function formatDose(amount?: string | null, unit?: string | null): string {
  if (amount == null || amount === '') return '—'
  const n = Number(amount)
  const value = Number.isFinite(n) ? String(n) : amount
  return unit ? `${value} ${unit}` : value
}

interface MarListProps {
  items: MarDueItem[]
  administeredIds: string[]
  onCheck: (item: MarDueItem) => void
}

/**
 * The MAR (Medication Administration Record): a patient's due medications.
 * Each order shows drug / dose / via / aprazamento; the nurse opens the BCMA
 * check from here, and administered items switch to an "Administrado" badge.
 */
export default function MarList({ items, administeredIds, onCheck }: MarListProps) {
  const done = new Set(administeredIds)
  return (
    <div className="overflow-x-auto rounded-lg border border-white bg-neu-panel">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-white">
            {['Medicamento', 'Dose', 'Via', 'Frequência', 'Ação'].map((h) => (
              <th
                key={h}
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const administered = done.has(item.id)
            return (
              <tr key={item.id} className="border-b border-white last:border-0">
                <td className="px-4 py-3">
                  <div className="font-medium text-neu-ink">{item.drug_name}</div>
                  {item.dosage_instructions && (
                    <div className="text-xs text-neu-inkMuted">{item.dosage_instructions}</div>
                  )}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {formatDose(item.dose_amount, item.dose_unit)}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">{item.route || '—'}</td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {item.frequency_per_day ? `${item.frequency_per_day}×/dia` : '—'}
                </td>
                <td className="px-4 py-3">
                  {administered ? (
                    <StatusBadge meta={ADMINISTERED_META} />
                  ) : (
                    <button
                      type="button"
                      onClick={() => onCheck(item)}
                      className="rounded-md border border-neu-brand bg-neu-brand px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
                    >
                      Checar
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
