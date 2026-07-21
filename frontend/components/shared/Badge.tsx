import type { HTMLAttributes } from 'react'

export type BadgeVariant = 'neutral' | 'brand' | 'success' | 'danger'

/**
 * Neumorphic badge primitive. Same anatomy as the topbar clinic badge in
 * `DashboardShell` (rounded-full pill, `bg` no token /10, borda /20, texto no
 * token). For workflow-status pills keep using `StatusBadge` +
 * `lib/operational-ui` — this primitive is for standalone, non-status labels.
 */
const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  neutral: 'border-neu-inkMuted/20 bg-neu-inkMuted/10 text-neu-inkSoft',
  brand: 'border-neu-brand/20 bg-neu-brand/10 text-neu-brand',
  success: 'border-neu-success/20 bg-neu-success/10 text-neu-success',
  danger: 'border-neu-danger/20 bg-neu-danger/10 text-neu-danger',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
}

export default function Badge({ variant = 'neutral', className = '', ...props }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${VARIANT_CLASSES[variant]} ${className}`.trim()}
      {...props}
    />
  )
}
