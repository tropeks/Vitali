'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch, ApiError } from '@/lib/api'

const initialForm = {
  full_name: '',
  social_name: '',
  cpf: '',
  cns: '',
  identity_document: '',
  identity_issuer: '',
  identity_state: '',
  birth_date: '',
  birth_city: '',
  birth_state: '',
  nationality: 'Brasileira',
  gender: 'N',
  race_color: '',
  marital_status: '',
  mother_name: '',
  father_name: '',
  occupation: '',
  education_level: '',
  preferred_language: 'pt-BR',
  blood_type: '',
  phone: '',
  whatsapp: '',
  email: '',
  address_street: '',
  address_number: '',
  address_complement: '',
  address_neighborhood: '',
  address_city: '',
  address_state: '',
  address_postal_code: '',
  emergency_name: '',
  emergency_relationship: '',
  emergency_phone: '',
  accessibility_mobility: '',
  accessibility_visual: '',
  accessibility_hearing: '',
  accessibility_notes: '',
  notes: '',
}

const genderOptions = [
  { value: 'N', label: 'Não informado' },
  { value: 'F', label: 'Feminino' },
  { value: 'M', label: 'Masculino' },
  { value: 'O', label: 'Outro' },
]

const bloodTypes = ['', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

const raceColorOptions = [
  { value: '', label: 'Não informada' },
  { value: 'white', label: 'Branca' },
  { value: 'black', label: 'Preta' },
  { value: 'brown', label: 'Parda' },
  { value: 'yellow', label: 'Amarela' },
  { value: 'indigenous', label: 'Indígena' },
]

const maritalStatusOptions = [
  { value: '', label: 'Não informado' },
  { value: 'single', label: 'Solteiro(a)' },
  { value: 'married', label: 'Casado(a)' },
  { value: 'stable_union', label: 'União estável' },
  { value: 'separated', label: 'Separado(a)' },
  { value: 'divorced', label: 'Divorciado(a)' },
  { value: 'widowed', label: 'Viúvo(a)' },
]

function onlyDigits(value: string) {
  return value.replace(/\D/g, '')
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (typeof error.body === 'string') return error.body
    const firstValue = Object.values(error.body ?? {})[0]
    if (Array.isArray(firstValue)) return String(firstValue[0])
    if (typeof firstValue === 'string') return firstValue
    return JSON.stringify(error.body)
  }
  return 'Erro ao cadastrar paciente.'
}

export default function NewPatientPage() {
  const router = useRouter()
  const [form, setForm] = useState(initialForm)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const setField = (field: keyof typeof form, value: string) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const payload: Record<string, unknown> = {
        ...form,
        cpf: onlyDigits(form.cpf),
        cns: onlyDigits(form.cns),
        social_name: form.social_name.trim(),
        phone: form.phone.trim(),
        whatsapp: form.whatsapp.trim(),
        email: form.email.trim(),
        notes: form.notes.trim(),
        identity_state: form.identity_state.trim().toUpperCase(),
        birth_state: form.birth_state.trim().toUpperCase(),
        address: {
          street: form.address_street.trim(), number: form.address_number.trim(),
          complement: form.address_complement.trim(), neighborhood: form.address_neighborhood.trim(),
          city: form.address_city.trim(), state: form.address_state.trim().toUpperCase(),
          postal_code: onlyDigits(form.address_postal_code),
        },
        emergency_contact: {
          name: form.emergency_name.trim(), relationship: form.emergency_relationship.trim(),
          phone: form.emergency_phone.trim(),
        },
        accessibility_needs: {
          mobility: form.accessibility_mobility.trim(), visual: form.accessibility_visual.trim(),
          hearing: form.accessibility_hearing.trim(), notes: form.accessibility_notes.trim(),
        },
      }
      const formOnlyKeys = [
        'address_street', 'address_number', 'address_complement', 'address_neighborhood',
        'address_city', 'address_state', 'address_postal_code', 'emergency_name',
        'emergency_relationship', 'emergency_phone', 'accessibility_mobility',
        'accessibility_visual', 'accessibility_hearing', 'accessibility_notes',
      ] as const
      formOnlyKeys.forEach((key) => delete payload[key])
      const patient = await apiFetch<{ id: string }>('/api/v1/patients/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      router.push(`/patients/${patient.id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => router.back()}
          className="text-sm text-slate-400 hover:text-slate-700"
        >
          ← Pacientes
        </button>
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Novo Paciente</h1>
          <p className="mt-1 text-sm text-slate-500">Cadastro completo para identificação segura e continuidade do cuidado.</p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form onSubmit={submit} className="space-y-5">
        <div className="neu-panel">
          <h2 className="text-sm font-bold text-slate-800">Identificação</h2>
          <div className="mt-4 grid grid-cols-12 gap-4">
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">Nome completo *</span>
              <input
                name="full_name"
                value={form.full_name}
                onChange={(event) => setField('full_name', event.target.value)}
                required
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">Nome social</span>
              <input
                name="social_name"
                value={form.social_name}
                onChange={(event) => setField('social_name', event.target.value)}
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">CPF *</span>
              <input
                name="cpf"
                value={form.cpf}
                onChange={(event) => setField('cpf', event.target.value)}
                required
                inputMode="numeric"
                placeholder="00000000000"
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">Data de nascimento *</span>
              <input
                name="birth_date"
                type="date"
                value={form.birth_date}
                onChange={(event) => setField('birth_date', event.target.value)}
                required
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-4 block">
              <span className="neu-label">CNS (Cartão SUS)</span>
              <input name="cns" value={form.cns} onChange={(e) => setField('cns', e.target.value)} inputMode="numeric" maxLength={18} className="neu-input" />
            </label>
            <label className="col-span-12 md:col-span-4 block">
              <span className="neu-label">Documento de identidade</span>
              <input name="identity_document" value={form.identity_document} onChange={(e) => setField('identity_document', e.target.value)} className="neu-input" />
            </label>
            <label className="col-span-8 md:col-span-3 block">
              <span className="neu-label">Órgão emissor</span>
              <input name="identity_issuer" value={form.identity_issuer} onChange={(e) => setField('identity_issuer', e.target.value)} className="neu-input" />
            </label>
            <label className="col-span-4 md:col-span-1 block">
              <span className="neu-label">UF</span>
              <input name="identity_state" value={form.identity_state} onChange={(e) => setField('identity_state', e.target.value)} maxLength={2} className="neu-input uppercase" />
            </label>
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">Gênero *</span>
              <select
                name="gender"
                value={form.gender}
                onChange={(event) => setField('gender', event.target.value)}
                className="neu-input"
              >
                {genderOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="col-span-12 md:col-span-6 block">
              <span className="neu-label">Tipo sanguíneo</span>
              <select
                name="blood_type"
                value={form.blood_type}
                onChange={(event) => setField('blood_type', event.target.value)}
                className="neu-input"
              >
                {bloodTypes.map((value) => (
                  <option key={value || 'empty'} value={value}>{value || 'Não informado'}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="neu-panel">
          <h2 className="text-sm font-bold text-slate-800">Dados sociodemográficos</h2>
          <p className="mt-1 text-xs text-slate-500">Informações opcionais para identificação segura e continuidade do cuidado.</p>
          <div className="mt-4 grid grid-cols-12 gap-4">
            <label className="col-span-12 md:col-span-5 block"><span className="neu-label">Naturalidade</span><input name="birth_city" value={form.birth_city} onChange={(e) => setField('birth_city', e.target.value)} className="neu-input" /></label>
            <label className="col-span-4 md:col-span-1 block"><span className="neu-label">UF</span><input name="birth_state" value={form.birth_state} onChange={(e) => setField('birth_state', e.target.value)} maxLength={2} className="neu-input uppercase" /></label>
            <label className="col-span-8 md:col-span-3 block"><span className="neu-label">Nacionalidade</span><input name="nationality" value={form.nationality} onChange={(e) => setField('nationality', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-3 block"><span className="neu-label">Idioma preferido</span><input name="preferred_language" value={form.preferred_language} onChange={(e) => setField('preferred_language', e.target.value)} placeholder="pt-BR" className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Raça/cor (autodeclarada)</span><select name="race_color" value={form.race_color} onChange={(e) => setField('race_color', e.target.value)} className="neu-input">{raceColorOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Estado civil</span><select name="marital_status" value={form.marital_status} onChange={(e) => setField('marital_status', e.target.value)} className="neu-input">{maritalStatusOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Escolaridade</span><input name="education_level" value={form.education_level} onChange={(e) => setField('education_level', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-6 block"><span className="neu-label">Nome da mãe</span><input name="mother_name" value={form.mother_name} onChange={(e) => setField('mother_name', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-6 block"><span className="neu-label">Nome do pai</span><input name="father_name" value={form.father_name} onChange={(e) => setField('father_name', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-6 block"><span className="neu-label">Ocupação</span><input name="occupation" value={form.occupation} onChange={(e) => setField('occupation', e.target.value)} className="neu-input" /></label>
          </div>
        </div>

        <div className="neu-panel">
          <h2 className="text-sm font-bold text-slate-800">Contato e endereço</h2>
          <div className="mt-4 grid grid-cols-12 gap-4">
            <label className="col-span-12 md:col-span-4 block">
              <span className="neu-label">Telefone</span>
              <input
                name="phone"
                value={form.phone}
                onChange={(event) => setField('phone', event.target.value)}
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-4 block">
              <span className="neu-label">WhatsApp</span>
              <input
                name="whatsapp"
                value={form.whatsapp}
                onChange={(event) => setField('whatsapp', event.target.value)}
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-4 block">
              <span className="neu-label">E-mail</span>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={(event) => setField('email', event.target.value)}
                className="neu-input"
              />
            </label>
            <label className="col-span-12 md:col-span-6 block"><span className="neu-label">Logradouro</span><input name="address_street" value={form.address_street} onChange={(e) => setField('address_street', e.target.value)} className="neu-input" /></label>
            <label className="col-span-4 md:col-span-2 block"><span className="neu-label">Número</span><input name="address_number" value={form.address_number} onChange={(e) => setField('address_number', e.target.value)} className="neu-input" /></label>
            <label className="col-span-8 md:col-span-4 block"><span className="neu-label">Complemento</span><input name="address_complement" value={form.address_complement} onChange={(e) => setField('address_complement', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Bairro</span><input name="address_neighborhood" value={form.address_neighborhood} onChange={(e) => setField('address_neighborhood', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Cidade</span><input name="address_city" value={form.address_city} onChange={(e) => setField('address_city', e.target.value)} className="neu-input" /></label>
            <label className="col-span-4 md:col-span-1 block"><span className="neu-label">UF</span><input name="address_state" value={form.address_state} onChange={(e) => setField('address_state', e.target.value)} maxLength={2} className="neu-input uppercase" /></label>
            <label className="col-span-8 md:col-span-3 block"><span className="neu-label">CEP</span><input name="address_postal_code" value={form.address_postal_code} onChange={(e) => setField('address_postal_code', e.target.value)} inputMode="numeric" className="neu-input" /></label>
          </div>
        </div>

        <div className="neu-panel">
          <h2 className="text-sm font-bold text-slate-800">Emergência e acessibilidade</h2>
          <div className="mt-4 grid grid-cols-12 gap-4">
            <label className="col-span-12 md:col-span-5 block"><span className="neu-label">Contato de emergência</span><input name="emergency_name" value={form.emergency_name} onChange={(e) => setField('emergency_name', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-3 block"><span className="neu-label">Vínculo</span><input name="emergency_relationship" value={form.emergency_relationship} onChange={(e) => setField('emergency_relationship', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Telefone de emergência</span><input name="emergency_phone" value={form.emergency_phone} onChange={(e) => setField('emergency_phone', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Mobilidade</span><input name="accessibility_mobility" value={form.accessibility_mobility} onChange={(e) => setField('accessibility_mobility', e.target.value)} placeholder="Ex.: cadeira de rodas" className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Necessidade visual</span><input name="accessibility_visual" value={form.accessibility_visual} onChange={(e) => setField('accessibility_visual', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 md:col-span-4 block"><span className="neu-label">Necessidade auditiva</span><input name="accessibility_hearing" value={form.accessibility_hearing} onChange={(e) => setField('accessibility_hearing', e.target.value)} className="neu-input" /></label>
            <label className="col-span-12 block"><span className="neu-label">Orientações de comunicação e acolhimento</span><textarea name="accessibility_notes" rows={2} value={form.accessibility_notes} onChange={(e) => setField('accessibility_notes', e.target.value)} className="neu-input resize-y" /></label>
          </div>
        </div>

        <div className="neu-panel">
          <label className="block">
            <span className="neu-label">Observações</span>
            <textarea
              name="notes"
              rows={4}
              value={form.notes}
              onChange={(event) => setField('notes', event.target.value)}
              className="w-full resize-y px-2 py-1.5 bg-neu-input border-transparent rounded-md text-xs shadow-neu-inset focus:outline-none focus:bg-white focus:ring-2 focus:ring-neu-brand/50 transition-all text-neu-ink"
            />
          </label>
        </div>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={() => router.push('/patients')}
            className="neu-btn-secondary"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="neu-btn-primary disabled:opacity-50"
          >
            {saving ? 'Salvando...' : 'Cadastrar paciente'}
          </button>
        </div>
      </form>
    </div>
  )
}
