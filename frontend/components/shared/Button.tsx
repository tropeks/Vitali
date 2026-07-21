import { forwardRef, type ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'

/**
 * Neumorphic button primitive (Tasy Neumorphic — docs/FRONTEND_GUIDELINES.md).
 * `primary`/`secondary` compose the canonical `.neu-btn-*` recipes from
 * `globals.css`; `danger` mirrors the primary anatomy on the `neu-danger`
 * token.
 *
 * Desvio anotado (danger): não existem tokens `dangerDeep`/`dangerEdge` nem
 * sombra `shadow-neu-btn-danger`, então o fim do gradiente usa `to-red-800`,
 * o edge superior `border-red-400` e a elevação `shadow-md`/`hover:shadow-lg`
 * (classes Tailwind padrão, sem literais hex).
 */
const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'neu-btn-primary',
  secondary: 'neu-btn-secondary',
  danger:
    'px-6 py-2 text-xs font-bold text-white bg-gradient-to-b from-neu-danger to-red-800 rounded-lg border-t border-red-400 shadow-md hover:shadow-lg transition-all',
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
