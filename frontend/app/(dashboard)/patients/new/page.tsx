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
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-slate-800">Identificação</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Nome completo *</span>
              <input
                name="full_name"
                value={form.full_name}
                onChange={(event) => setField('full_name', event.target.value)}
                required
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Nome social</span>
              <input
                name="social_name"
                value={form.social_name}
                onChange={(event) => setField('social_name', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">CPF *</span>
              <input
                name="cpf"
                value={form.cpf}
                onChange={(event) => setField('cpf', event.target.value)}
                required
                inputMode="numeric"
                placeholder="00000000000"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Data de nascimento *</span>
              <input
                name="birth_date"
                type="date"
                value={form.birth_date}
                onChange={(event) => setField('birth_date', event.target.value)}
                required
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Gênero *</span>
              <select
                name="gender"
                value={form.gender}
                onChange={(event) => setField('gender', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              >
                {genderOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Tipo sanguíneo</span>
              <select
                name="blood_type"
                value={form.blood_type}
                onChange={(event) => setField('blood_type', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              >
                {bloodTypes.map((value) => (
                  <option key={value || 'empty'} value={value}>{value || 'Não informado'}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-slate-800">Contato</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Telefone</span>
              <input
                name="phone"
                value={form.phone}
                onChange={(event) => setField('phone', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">WhatsApp</span>
              <input
                name="whatsapp"
                value={form.whatsapp}
                onChange={(event) => setField('whatsapp', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">E-mail</span>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={(event) => setField('email', event.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
            </label>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <label className="space-y-1 text-sm">
            <span className="font-medium text-slate-700">Observações</span>
            <textarea
              name="notes"
              rows={4}
              value={form.notes}
              onChange={(event) => setField('notes', event.target.value)}
              className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={() => router.push('/patients')}
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Salvando...' : 'Cadastrar paciente'}
          </button>
        </div>
      </form>
    </div>
  )
}
