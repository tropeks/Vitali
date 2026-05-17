import type { BadgeMeta } from '@/lib/operational-ui'

/**
 * The single bordered status pill used across every operational surface.
 * `meta` comes from a canonical map in `lib/operational-ui` — never inline
 * status colours at the call site. `label` overrides the canonical label
 * when the server returns a localized `status_display`.
 */
interface StatusBadgeProps {
  meta: Pick<BadgeMeta, 'label' | 'badgeClass'>
  label?: string | null
  className?: string
}

export default function StatusBadge({ meta, label, className = '' }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass} ${className}`.trim()}
    >
      {label || meta.label}
    </span>
  )
}
