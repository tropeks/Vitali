// Colocated types + label maps for the A4/A6 laboratory surfaces
// (LOINC + delta check, faturar lab→TISS). Kept in sync with the OpenAPI
// LabTest / LabOrderItem / LabDeltaAlert schemas.

export interface LabTestComponent {
  code?: string;
  name: string;
  unit?: string;
  reference_range?: string;
}

export interface LabTest {
  id: string;
  code: string;
  name: string;
  specimen_type: string;
  unit: string;
  reference_range: string;
  active: boolean;
  category?: string;
  category_display?: string;
  result_type?: string;
  result_type_display?: string;
  method?: string;
  /** A4 — LOINC terminology code (writable). */
  loinc_code?: string;
  /** A4 — percentage variation that triggers a delta alert. NULL = inert. */
  delta_threshold_pct?: string | null;
  components?: LabTestComponent[];
}

/** Autocomplete row from GET /api/v1/terminology/loinc/?q= */
export interface LoincResult {
  system: string;
  code: string;
  display: string;
  active: boolean;
  context?: string | null;
}

/** Nested read-only alert on a LabOrderItem (and /api/v1/lab-delta-alerts/). */
export interface LabDeltaAlert {
  id: string;
  order_item?: string;
  previous_item?: string | null;
  test?: string;
  previous_value: string;
  current_value: string;
  delta_absolute: string;
  delta_pct: string;
  threshold_pct: string;
  created_at: string;
}

export const categoryLabels: Record<string, string> = {
  hematology: "Hematologia",
  biochemistry: "Bioquímica",
  immunology: "Imunologia e sorologia",
  hormones: "Hormônios",
  microbiology: "Microbiologia",
  urinalysis: "Urinálise",
  parasitology: "Parasitologia",
  coagulation: "Coagulação",
  toxicology: "Toxicologia",
  molecular: "Genética e molecular",
  pathology: "Anatomia patológica",
  rapid_test: "Testes rápidos",
  other: "Outros",
};

export const resultTypeLabels: Record<string, string> = {
  numeric: "Numérico",
  qualitative: "Qualitativo",
  text: "Texto",
  panel: "Painel",
  microbiology: "Microbiologia",
};
