/**
 * Shared formatting helpers for Vitali frontend.
 */

/**
 * Formats a raw digit string as a Brazilian CPF mask: XXX.XXX.XXX-XX
 * Strips non-digits, caps at 11 digits, applies mask progressively.
 */
export function formatCPF(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 11)
  return digits
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1-$2')
}
