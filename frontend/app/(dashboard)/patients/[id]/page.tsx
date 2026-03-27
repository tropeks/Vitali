'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'

const SEVERITY_COLORS: Record<string, string> = {
  life_threatening: 'bg-red-100 text-red-800 border-red-200',
  severe: 'bg-orange-100 text-orange-800 border-orange-200',
  moderate: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  mild: 'bg-green-100 text-green-800 border-green-200',
}

export default function PatientDetailPage() {
  const { id } = useParams()
  const router = useRouter()
  const [patient, setPatient] = useState<any>(null)
  const [activeTab, setActiveTab] = useState('dados')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/v1/patients/${id}`)
      .then(r => r.json())
      .then(data => { setPatient(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [id])

  if (loading) return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-gray-100 rounded w-1/3"/>
      <div className="h-32 bg-gray-100 rounded"/>
    </div>
  )
  if (!patient) return <div className="text-center py-12 text-gray-400">Paciente não encontrado.</div>

  const tabs = [
    { id: 'dados', label: 'Dados Pessoais' },
    { id: 'alergias', label: `Alergias ${patient.allergies?.length ? `(${patient.allergies.length})` : ''}` },
    { id: 'historico', label: 'Histórico Médico' },
    { id: 'timeline', label: 'Timeline' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button onClick={() => router.back()} className="mt-1 text-gray-400 hover:text-gray-600">←</button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-semibold text-lg">
              {patient.full_name[0]}
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-900">{patient.full_name}</h1>
              {patient.social_name && <p className="text-sm text-gray-500">Nome social: {patient.social_name}</p>}
              <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                <span className="font-mono">{patient.medical_record_number}</span>
                <span>·</span>
                <span>{patient.age} anos</span>
                <span>·</span>
                <span>{patient.gender}</span>
                {patient.blood_type && <><span>·</span><span className="font-medium text-red-600">{patient.blood_type}</span></>}
              </div>
            </div>
          </div>
          {/* Allergy alert bar */}
          {patient.allergies?.some((a: any) => a.status === 'active' && a.severity === 'life_threatening') && (
            <div className="mt-3 px-4 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium">
              ⚠️ Alergia com risco de vida: {patient.allergies.filter((a: any) => a.severity === 'life_threatening').map((a: any) => a.substance).join(', ')}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-6">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'dados' && (
        <div className="grid grid-cols-2 gap-6">
          {[
            ['CPF', patient.cpf_masked ?? '***.***.***-**'],
            ['Data de Nascimento', patient.birth_date ? new Date(patient.birth_date+'T00:00:00').toLocaleDateString('pt-BR') : '—'],
            ['Gênero', patient.gender_display ?? patient.gender],
            ['Tipo Sanguíneo', patient.blood_type || '—'],
            ['Telefone', patient.phone || '—'],
            ['WhatsApp', patient.whatsapp || '—'],
            ['E-mail', patient.email || '—'],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</dt>
              <dd className="mt-1 text-sm text-gray-900">{value}</dd>
            </div>
          ))}
          {patient.address?.street && (
            <div className="col-span-2">
              <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide">Endereço</dt>
              <dd className="mt-1 text-sm text-gray-900">
                {patient.address.street}, {patient.address.number}{patient.address.complement ? ` - ${patient.address.complement}` : ''}, {patient.address.neighborhood}, {patient.address.city}/{patient.address.state}
              </dd>
            </div>
          )}
        </div>
      )}

      {activeTab === 'alergias' && (
        <div className="space-y-3">
          {patient.allergies?.length === 0 ? (
            <p className="text-sm text-gray-400">Nenhuma alergia registrada.</p>
          ) : patient.allergies?.map((a: any) => (
            <div key={a.id} className={`flex items-start gap-3 p-3 rounded-lg border ${SEVERITY_COLORS[a.severity] ?? 'bg-gray-50 border-gray-200'}`}>
              <div className="flex-1">
                <span className="font-medium text-sm">{a.substance}</span>
                {a.reaction && <p className="text-xs mt-0.5 opacity-75">{a.reaction}</p>}
              </div>
              <span className="text-xs font-medium">{a.severity_display}</span>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'historico' && (
        <div className="space-y-2">
          {patient.medical_history?.length === 0 ? (
            <p className="text-sm text-gray-400">Nenhum histórico registrado.</p>
          ) : patient.medical_history?.map((h: any) => (
            <div key={h.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
              <div>
                <span className="text-sm font-medium text-gray-900">{h.condition}</span>
                {h.cid10_code && <span className="ml-2 text-xs text-gray-400 font-mono">{h.cid10_code}</span>}
                <p className="text-xs text-gray-500 mt-0.5">{h.type_display}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                h.status === 'active' ? 'bg-red-100 text-red-700' :
                h.status === 'controlled' ? 'bg-yellow-100 text-yellow-700' : 'bg-green-100 text-green-700'
              }`}>{h.status_display}</span>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'timeline' && (
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">Timeline disponível no Sprint 4 com atendimentos clínicos.</p>
        </div>
      )}
    </div>
  )
}
