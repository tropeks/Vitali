import type { ReactNode } from 'react'
import type { OperationalTone } from '@/lib/operational-ui'

/**
 * Operational metric tile. Numbers use `font-semibold` (canonical — the
 * operational camp previously drifted to `font-bold`). Pass `tone` to tint
 * the whole tile for at-a-glance triage strips; omit it for neutral white.
 */
interface KpiTileProps {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: OperationalTone
  className?: string
}

const TILE_TONE: Record<OperationalTone, { wrap: string; label: string; value: string }> = {
  neutral: { wrap: 'border-slate-200 bg-white', label: 'text-slate-500', value: 'text-slate-800' },
  info: { wrap: 'border-blue-200 bg-blue-50', label: 'text-blue-700', value: 'text-blue-900' },
  attention: {
    wrap: 'border-yellow-200 bg-yellow-50',
    label: 'text-yellow-700',
    value: 'text-yellow-800',
  },
  success: {
    wrap: 'border-green-200 bg-green-50',
    label: 'text-green-700',
    value: 'text-green-800',
  },
  critical: { wrap: 'border-red-200 bg-red-50', label: 'text-red-700', value: 'text-red-700' },
}

export default function KpiTile({
  label,
  value,
  hint,
  icon,
  tone = 'neutral',
  className = '',
}: KpiTileProps) {
  const t = TILE_TONE[tone]
  return (
    <div className={`rounded-lg border p-4 ${t.wrap} ${className}`.trim()}>
      <div
        className={`flex items-center gap-2 text-xs font-semibold uppercase tracking-wide ${t.label}`}
      >
        {icon}
        {label}
      </div>
      <p className={`mt-2 text-2xl font-semibold ${t.value}`}>{value}</p>
      {hint != null && <p className={`mt-1 text-xs ${t.label}`}>{hint}</p>}
    </div>
  )
}
