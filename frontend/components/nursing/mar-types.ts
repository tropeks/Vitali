/**
 * Types for the MAR / checagem beira-leito (BCMA) surface (N5).
 *
 * Surfaces the N3 BCMA backend: the "5 certos" bedside verifier
 * (`POST /api/v1/emar/check/`) plus the medication orders that make up a
 * patient's due list (`/api/v1/prescriptions/` → `items[]`).
 */

/** A patient resolved from a bedside scan (wristband barcode or MRN). */
export interface MarPatient {
  id: string
  full_name: string
  medical_record_number?: string | null
}

/**
 * A due medication for the MAR: a signed `PrescriptionItem`. `id` is the
 * `prescription_item` uuid the BCMA check is run against.
 */
export interface MarDueItem {
  id: string
  prescription: string
  drug_name: string
  dose_amount?: string | null
  dose_unit?: string | null
  route?: string | null
  frequency_per_day?: number | null
  dosage_instructions?: string | null
}

/** A prescription as returned by `/api/v1/prescriptions/` (the fields we read). */
export interface MarPrescription {
  id: string
  is_signed?: boolean | null
  status?: string | null
  items?: MarDueItem[] | null
}

/**
 * The structured verdict of the "5 certos" — returned inside the 422 body of
 * `POST /api/v1/emar/check/` (`FiveRightsResult.as_dict()` on the backend).
 */
export interface FiveRights {
  patient: boolean
  medication: boolean
  dose: boolean
  route: boolean
  time: boolean
  ok: boolean
  mismatches: string[]
}

/** 422 body when a right fails and no override was supplied. */
export interface BcmaCheckError {
  detail: string
  bcma: FiveRights
}

/** 201 body: the recorded `MedicationAdministration` (fields we surface). */
export interface MedicationAdministrationRecord {
  id: string
  status: string
  bcma_verified: boolean
}

/** The five rights in canonical order, matching the backend verifier. */
export const FIVE_RIGHTS_ORDER = [
  'patient',
  'medication',
  'dose',
  'route',
  'time',
] as const

export type RightKey = (typeof FIVE_RIGHTS_ORDER)[number]

/** pt-BR labels for each right. */
export const RIGHT_LABELS: Record<RightKey, string> = {
  patient: 'Paciente',
  medication: 'Medicamento',
  dose: 'Dose',
  route: 'Via',
  time: 'Hora',
}
