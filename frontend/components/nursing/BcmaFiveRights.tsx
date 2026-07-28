import { FIVE_RIGHTS_ORDER, RIGHT_LABELS, type FiveRights } from './mar-types'

/**
 * The "5 certos" breakdown (paciente / medicamento / dose / via / hora).
 *
 * Renders the structured verdict from the BCMA check — each right shows
 * "Certo" (passed) or "Falhou" (failed), and failed rows are highlighted in
 * red so the nurse sees exactly which right blocked the administration.
 */
export default function BcmaFiveRights({ result }: { result: FiveRights }) {
  return (
    <div className="space-y-1.5" role="list" aria-label="Checagem dos 5 certos">
      {FIVE_RIGHTS_ORDER.map((right) => {
        const passed = result[right]
        return (
          <div
            key={right}
            role="listitem"
            data-testid={`bcma-right-${right}`}
            className={`flex items-center justify-between rounded-md border px-3 py-2 text-sm ${
              passed
                ? 'border-slate-200 bg-neu-panel text-neu-ink'
                : 'border-red-300 bg-red-50 text-red-800'
            }`}
          >
            <span className="font-medium">{RIGHT_LABELS[right]}</span>
            <span
              className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
                passed
                  ? 'border-green-200 bg-green-100 text-green-700'
                  : 'border-red-200 bg-red-100 text-red-700'
              }`}
            >
              {passed ? 'Certo' : 'Falhou'}
            </span>
          </div>
        )
      })}
    </div>
  )
}
