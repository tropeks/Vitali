'use client'

import MicrobiologyPanel from './MicrobiologyPanel'
import PathologyPanel from './PathologyPanel'

interface Props {
  patientId: string
  /** `emr.read` — gates both microbiology and pathology reads. */
  canRead: boolean
}

/**
 * Aba "Lab especializado" do prontuário: microbiologia estruturada (culturas +
 * antibiograma S/I/R) e anatomia patológica (laudos + espécimes), lado a lado.
 * Read-only; o backend enforça emr.read.
 */
export default function LabEspecializadoTab({ patientId, canRead }: Props) {
  return (
    <div className="space-y-6">
      <section aria-label="Microbiologia">
        <h3 className="mb-3 text-base font-semibold text-neu-ink">Microbiologia</h3>
        <MicrobiologyPanel patientId={patientId} canRead={canRead} />
      </section>

      <section aria-label="Anatomia patológica">
        <h3 className="mb-3 text-base font-semibold text-neu-ink">Anatomia patológica</h3>
        <PathologyPanel patientId={patientId} canRead={canRead} />
      </section>
    </div>
  )
}
