import { forwardRef, type ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'

/**
 * Neumorphic button primitive (Tasy Neumorphic — docs/FRONTEND_GUIDELINES.md).
 * `primary`/`secondary` compose the canonical `.neu-btn-*` recipes from
 * `globals.css`; `danger` mirrors the primary anatomy 1:1 on the danger
 * tokens (`neu-danger` → `neu-dangerDeep` gradient, `neu-dangerEdge` top
 * border, `shadow-neu-btn-danger(-hover)` elevation).
 */
const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'neu-btn-primary',
  secondary: 'neu-btn-secondary',
  danger:
    'px-6 py-2 text-xs font-bold text-white bg-gradient-to-b from-neu-danger to-neu-dangerDeep rounded-lg border-t border-neu-dangerEdge shadow-neu-btn-danger hover:shadow-neu-btn-danger-hover transition-all',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', className = '', ...props },
  ref
) {
  return (
    <button
      ref={ref}
      className={`${VARIANT_CLASSES[variant]} disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 ${className}`.trim()}
      {...props}
    />
  )
})

export default Button
