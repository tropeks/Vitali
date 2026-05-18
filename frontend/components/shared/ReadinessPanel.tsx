import { Search } from 'lucide-react'

/**
 * "Prontidão" panel — the readiness/blockers summary shared by the workbench
 * closing panels (TISS guide, dispensação). When there are no blockers the
 * panel states it can proceed; otherwise it lists every blocker explicitly.
 */
interface ReadinessPanelProps {
  blockers: string[]
  readyText: string
  title?: string
}

export default function ReadinessPanel({
  blockers,
  readyText,
  title = 'Prontidão',
}: ReadinessPanelProps) {
  const ready = blockers.length === 0
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Search size={15} />
        {title}
      </div>
      {ready ? (
        <p className="text-sm text-green-700">{readyText}</p>
      ) : (
        <ul className="space-y-1 text-sm text-yellow-800">
          {blockers.map((blocker) => (
            <li key={blocker} className="flex gap-2">
              <span aria-hidden="true">-</span>
              <span>{blocker}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
