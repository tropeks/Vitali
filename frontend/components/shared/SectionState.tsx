import type { ReactNode } from 'react'

/**
 * Inline empty / degraded / informational state block. Replaces the
 * per-screen copies of this pattern. `tone` carries the meaning; the text
 * always states it explicitly (status text is mandatory).
 */
interface SectionStateProps {
  title: string
  detail: string
  tone?: 'neutral' | 'success' | 'warning' | 'critical'
  action?: ReactNode
}

const STYLES = {
  neutral: 'border-slate-200 bg-white text-slate-700',
  success: 'border-green-200 bg-green-50 text-green-800',
  warning: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  critical: 'border-red-200 bg-red-50 text-red-800',
} as const

export default function SectionState({
  title,
  detail,
  tone = 'neutral',
  action,
}: SectionStateProps) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${STYLES[tone]}`}>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs opacity-80">{detail}</p>
      {action != null && <div className="mt-3">{action}</div>}
    </div>
  )
}
