import type { BadgeMeta } from '@/lib/operational-ui'

/**
 * The single bordered status pill used across every operational surface.
 * `meta` comes from a canonical map in `lib/operational-ui` — never inline
 * status colours at the call site.
 *
 * `label` is an OVERRIDE for an already contract-resolved display string
 * (e.g. `appointmentBadgeLabel(status, status_display)` — canonical for a
 * known status, server display only for unknown). Do NOT pass a raw server
 * `status_display` directly: that would relabel known canonical statuses and
 * break the single-source-of-truth rule. Omit `label` to render `meta.label`.
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
