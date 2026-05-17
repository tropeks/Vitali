import type { ReactNode } from 'react'

/**
 * Canonical page shells (DESIGN.md v2 — "Hybrid by screen type").
 *
 * - `workbench`  — focused form / order-entry flows. Content is capped at
 *   1500px and centred so dense forms stay readable on ultrawide monitors.
 *   Owns its own `bg-slate-50` and vertical rhythm (`space-y-4`).
 * - `operational` — queue / table-heavy dashboards. Full-bleed to maximise
 *   dense-table real estate, looser rhythm (`space-y-5`).
 *
 * Screens must not hand-roll these wrappers; pick a variant instead.
 */
export type PageShellVariant = 'workbench' | 'operational'

interface PageShellProps {
  variant: PageShellVariant
  children: ReactNode
  className?: string
}

export default function PageShell({ variant, children, className = '' }: PageShellProps) {
  if (variant === 'workbench') {
    return (
      <div className="min-h-full bg-slate-50">
        <div className={`mx-auto max-w-[1500px] space-y-4 ${className}`.trim()}>{children}</div>
      </div>
    )
  }
  return <div className={`space-y-5 ${className}`.trim()}>{children}</div>
}
