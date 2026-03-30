'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { SOAPEditor } from '@/components/encounters/SOAPEditor';
import { getAccessToken } from '@/lib/auth';
import Link from 'next/link';

interface VitalSigns {
  id: number;
  weight_kg: string | null;
  height_cm: string | null;
  blood_pressure_systolic: number | null;
  blood_pressure_diastolic: number | null;
  heart_rate: number | null;
  temperature_celsius: string | null;
  oxygen_saturation: number | null;
  bmi: number | null;
}

interface ClinicalDocument {
  id: string;
  doc_type: string;
  doc_type_display: string;
  content: string;
  is_signed: boolean;
  signed_at: string | null;
  signed_by_name: string | null;
  created_at: string;
}

interface Encounter {
  id: string;
  patient: string;
  patient_detail: {
    full_name: string;
    medical_record_number: string;
    birth_date: string;
    gender_display: string;
    allergies: { id: string; substance: string; severity: string; severity_display: string }[];
  };
  professional_name: string;
  professional_specialty: string;
  encounter_date: string;
  status: 'open' | 'signed' | 'cancelled';
  status_display: string;
  chief_complaint: string;
  soap_note: {
    id: number;
    encounter: string;
    subjective: string;
    objective: string;
    assessment: string;
    plan: string;
    cid10_codes: string[];
    updated_at: string;
  } | null;
  vital_signs: VitalSigns | null;
  documents: ClinicalDocument[];
}

const STATUS_STYLES: Record<string, string> = {
  open: 'bg-yellow-100 text-yellow-800',
  signed: 'bg-green-100 text-green-800',
  cancelled: 'bg-gray-100 text-gray-500',
};

async function apiFetch(path: string) {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function apiPost(path: string, body?: Record<string, unknown>) {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function apiPatch(path: string, body: Record<string, unknown>) {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function VitalSignsForm({ vs, encounterId, readOnly }: { vs: VitalSigns | null; encounterId: string; readOnly: boolean }) {
  const [vals, setVals] = useState({
    weight_kg: vs?.weight_kg ?? '',
    height_cm: vs?.height_cm ?? '',
    blood_pressure_systolic: vs?.blood_pressure_systolic?.toString() ?? '',
    blood_pressure_diastolic: vs?.blood_pressure_diastolic?.toString() ?? '',
    heart_rate: vs?.heart_rate?.toString() ?? '',
    temperature_celsius: vs?.temperature_celsius ?? '',
    oxygen_saturation: vs?.oxygen_saturation?.toString() ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    if (!vs?.id) return;
    setSaving(true);
    try {
      await apiPatch(`/vital-signs/${vs.id}/`, Object.fromEntries(
        Object.entries(vals).map(([k, v]) => [k, v === '' ? null : v])
      ));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch { alert('Erro ao salvar sinais vitais'); }
    finally { setSaving(false); }
  };

  const Field = ({ label, field, unit }: { label: string; field: keyof typeof vals; unit?: string }) => (
    <div>
      <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={vals[field]}
          onChange={e => setVals(v => ({ ...v, [field]: e.target.value }))}
          readOnly={readOnly}
          className={`w-full border rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none ${readOnly ? 'bg-gray-50' : ''}`}
          step="any"
        />
        {unit && <span className="text-xs text-gray-400 whitespace-nowrap">{unit}</span>}
      </div>
    </div>
  );

  const bmi = vals.weight_kg && vals.height_cm
    ? (parseFloat(vals.weight_kg as string) / Math.pow(parseFloat(vals.height_cm as string) / 100, 2)).toFixed(1)
    : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Sinais Vitais</h3>
        {!readOnly && (
          <button
            onClick={save}
            disabled={saving}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            {saving ? 'Salvando...' : saved ? '✓ Salvo' : 'Salvar'}
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Peso" field="weight_kg" unit="kg" />
        <Field label="Altura" field="height_cm" unit="cm" />
        <Field label="PA Sistólica" field="blood_pressure_systolic" unit="mmHg" />
        <Field label="PA Diastólica" field="blood_pressure_diastolic" unit="mmHg" />
        <Field label="FC" field="heart_rate" unit="bpm" />
        <Field label="Temperatura" field="temperature_celsius" unit="°C" />
        <Field label="SpO₂" field="oxygen_saturation" unit="%" />
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">IMC</label>
          <div className="border rounded-lg px-2 py-1.5 text-sm bg-gray-50 text-gray-600">{bmi ?? '—'}</div>
        </div>
      </div>
    </div>
  );
}

function DocumentsPanel({ documents, encounterId, readOnly, onRefresh }: {
  documents: ClinicalDocument[];
  encounterId: string;
  readOnly: boolean;
  onRefresh: () => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [docType, setDocType] = useState('certificate');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);

  const createDoc = async () => {
    setSaving(true);
    try {
      await apiPost('/documents/', { encounter: encounterId, doc_type: docType, content });
      setShowForm(false);
      setContent('');
      onRefresh();
    } catch { alert('Erro ao criar documento'); }
    finally { setSaving(false); }
  };

  const signDoc = async (docId: string) => {
    if (!confirm('Assinar este documento? Esta ação não pode ser desfeita.')) return;
    try {
      await apiPost(`/documents/${docId}/sign/`);
      onRefresh();
    } catch { alert('Erro ao assinar documento'); }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Documentos</h3>
        {!readOnly && (
          <button
            onClick={() => setShowForm(s => !s)}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            + Novo Documento
          </button>
        )}
      </div>

      {showForm && (
        <div className="border rounded-lg p-3 space-y-2 bg-gray-50">
          <select
            value={docType}
            onChange={e => setDocType(e.target.value)}
            className="w-full border rounded px-2 py-1.5 text-sm"
          >
            <option value="certificate">Atestado Médico</option>
            <option value="prescription">Receita</option>
            <option value="referral">Encaminhamento</option>
            <option value="exam_request">Solicitação de Exame</option>
            <option value="report">Laudo</option>
          </select>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={4}
            placeholder="Conteúdo do documento..."
            className="w-full border rounded px-2 py-1.5 text-sm resize-y"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs text-gray-500">Cancelar</button>
            <button
              onClick={createDoc}
              disabled={!content || saving}
              className="bg-blue-600 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
          </div>
        </div>
      )}

      {documents.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-4">Nenhum documento nesta consulta</p>
      ) : (
        <div className="space-y-2">
          {documents.map(doc => (
            <div key={doc.id} className="border rounded-lg p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-800">{doc.doc_type_display}</span>
                {doc.is_signed ? (
                  <span className="text-xs text-green-600 font-medium">✓ Assinado</span>
                ) : (
                  !readOnly && (
                    <button
                      onClick={() => signDoc(doc.id)}
                      className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                    >
                      Assinar
                    </button>
                  )
                )}
              </div>
              <p className="text-xs text-gray-500 line-clamp-2">{doc.content}</p>
              {doc.is_signed && doc.signed_by_name && (
                <p className="text-xs text-gray-400">
                  Assinado por {doc.signed_by_name} em {format(new Date(doc.signed_at!), "dd/MM/yyyy 'às' HH:mm", { locale: ptBR })}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const GUIDE_STATUS_STYLES: Record<string, string> = {
  draft:     'bg-gray-100 text-gray-600',
  pending:   'bg-yellow-100 text-yellow-700',
  submitted: 'bg-blue-100 text-blue-700',
  paid:      'bg-green-100 text-green-700',
  denied:    'bg-red-100 text-red-700',
  appeal:    'bg-orange-100 text-orange-700',
};

function FaturamentoCard({ encounterId }: { encounterId: string }) {
  const [guides, setGuides] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setLoading(false); return; }
    fetch(`/api/v1/billing/guides/?encounter=${encounterId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => {
        if (r.status === 403) { setHidden(true); return null; }
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then(data => {
        if (!data) return;
        setGuides(Array.isArray(data) ? data : data.results ?? []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [encounterId]);

  if (hidden) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Faturamento</h3>
        <Link
          href={`/billing/guides/new?encounter=${encounterId}`}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          + Nova Guia TISS
        </Link>
      </div>

      {loading ? (
        <div className="h-8 bg-gray-100 rounded animate-pulse" />
      ) : guides.length === 0 ? (
        <div className="text-center py-4 space-y-3">
          <p className="text-xs text-gray-400">Nenhuma guia TISS criada.</p>
          <Link
            href={`/billing/guides/new?encounter=${encounterId}`}
            className="inline-block bg-blue-600 text-white text-xs px-4 py-2 rounded-lg font-medium hover:bg-blue-700"
          >
            Criar Guia TISS →
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          {guides.map((g: any) => (
            <Link
              key={g.id}
              href={`/billing/guides/${g.id}`}
              className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 group"
            >
              <span className="text-sm font-mono text-gray-800 group-hover:text-blue-600">
                Guia #{g.guide_number}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${GUIDE_STATUS_STYLES[g.status] ?? 'bg-gray-100 text-gray-600'}`}>
                {g.status_display}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function EncounterDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [encounter, setEncounter] = useState<Encounter | null>(null);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);

  const load = async () => {
    try {
      const data = await apiFetch(`/encounters/${id}/`);
      setEncounter(data);
    } catch { router.push('/encounters'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [id]);

  const signEncounter = async () => {
    if (!confirm('Assinar esta consulta? Ela ficará somente leitura após assinatura.')) return;
    setSigning(true);
    try {
      const updated = await apiPost(`/encounters/${id}/sign/`);
      setEncounter(updated);
    } catch { alert('Erro ao assinar consulta'); }
    finally { setSigning(false); }
  };

  if (loading) return <div className="p-6 text-gray-400 text-sm">Carregando...</div>;
  if (!encounter) return null;

  const patient = encounter.patient_detail;
  const lifeThreateningAllergies = patient.allergies.filter(a => a.severity === 'life_threatening');
  const isReadOnly = encounter.status !== 'open';

  return (
    <div className="p-6 space-y-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <button onClick={() => router.push('/encounters')} className="text-gray-400 hover:text-gray-600 text-sm">
              ← Consultas
            </button>
          </div>
          <h1 className="text-xl font-bold text-gray-900">{patient.full_name}</h1>
          <p className="text-sm text-gray-500">
            {encounter.professional_name} {encounter.professional_specialty && `· ${encounter.professional_specialty}`} ·{' '}
            {format(new Date(encounter.encounter_date), "dd 'de' MMMM 'de' yyyy 'às' HH:mm", { locale: ptBR })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${STATUS_STYLES[encounter.status]}`}>
            {encounter.status_display}
          </span>
          {!isReadOnly && (
            <button
              onClick={signEncounter}
              disabled={signing}
              className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
            >
              {signing ? 'Assinando...' : 'Assinar Consulta'}
            </button>
          )}
        </div>
      </div>

      {/* Life-threatening allergy alert */}
      {lifeThreateningAllergies.length > 0 && (
        <div className="bg-red-50 border border-red-300 rounded-xl p-4 flex items-start gap-3">
          <span className="text-red-500 text-xl">⚠️</span>
          <div>
            <p className="font-semibold text-red-700 text-sm">Alergia de Risco de Vida</p>
            <p className="text-red-600 text-sm">{lifeThreateningAllergies.map(a => a.substance).join(', ')}</p>
          </div>
        </div>
      )}

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left column */}
        <div className="space-y-4">
          {/* Patient card */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-700">Dados do Paciente</h3>
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Prontuário</span>
                <span className="font-mono font-medium text-gray-800">{patient.medical_record_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Nascimento</span>
                <span className="text-gray-800">{format(new Date(patient.birth_date), 'dd/MM/yyyy')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Sexo</span>
                <span className="text-gray-800">{patient.gender_display}</span>
              </div>
              {patient.allergies.length > 0 && (
                <div className="pt-2 border-t border-gray-100">
                  <p className="text-gray-500 mb-1.5">Alergias</p>
                  <div className="flex flex-wrap gap-1">
                    {patient.allergies.map(a => (
                      <span
                        key={a.id}
                        className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          a.severity === 'life_threatening' ? 'bg-red-100 text-red-700' :
                          a.severity === 'severe' ? 'bg-orange-100 text-orange-700' :
                          a.severity === 'moderate' ? 'bg-yellow-100 text-yellow-700' :
                          'bg-blue-100 text-blue-700'
                        }`}
                      >
                        {a.substance}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Vital signs */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <VitalSignsForm
              vs={encounter.vital_signs}
              encounterId={id}
              readOnly={isReadOnly}
            />
          </div>

          {/* Documents */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <DocumentsPanel
              documents={encounter.documents}
              encounterId={id}
              readOnly={isReadOnly}
              onRefresh={load}
            />
          </div>

          {/* Faturamento */}
          <FaturamentoCard encounterId={id} />
        </div>

        {/* Right column — SOAP */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <SOAPEditor soapNote={encounter.soap_note} readOnly={isReadOnly} />
          </div>
        </div>
      </div>
    </div>
  );
}
