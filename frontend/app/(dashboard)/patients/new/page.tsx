'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch, ApiError } from '@/lib/api'

const initialForm = {
  full_name: '',
  social_name: '',
  cpf: '',
  birth_date: '',
  gender: 'N',
  blood_type: '',
  phone: '',
  whatsapp: '',
  email: '',
  notes: '',
}

const genderOptions = [
  { value: 'N', label: 'Não informado' },
  { value: 'F', label: 'Feminino' },
  { value: 'M', label: 'Masculino' },
  { value: 'O', label: 'Outro' },
]

const bloodTypes = ['', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

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
      const payload = {
        ...form,
        cpf: onlyDigits(form.cpf),
        social_name: form.social_name.trim(),
        phone: form.phone.trim(),
        whatsapp: form.whatsapp.trim(),
        email: form.email.trim(),
        notes: form.notes.trim(),
      }
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
          <p className="mt-1 text-sm text-slate-500">Cadastro mínimo para atendimento, agenda e faturamento.</p>
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
          <h2 className="text-sm font-bold text-slate-800">Contato</h2>
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
