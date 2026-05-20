'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle,
  FileText,
  Phone,
  Plus,
  Search,
  ShieldAlert,
  UserRound,
  Users,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { summarizePatients } from '@/lib/operational-ui'

interface Patient {
  id: string
  full_name: string
  social_name?: string | null
  medical_record_number?: string | null
  birth_date?: string | null
  age?: number | null
  phone?: string | null
  whatsapp?: string | null
  active_allergies_count?: number | null
  is_active?: boolean | null
}

interface PatientListResponse {
  results?: Patient[]
  count?: number
}

function PatientTableSkeleton() {
  return (
    <>
      {Array.from({ length: 6 }).map((_, i) => (
        <tr key={i}>
          <td colSpan={6} className="px-4 py-3">
            <div className="h-4 w-3/4 animate-pulse rounded bg-slate-100" />
          </td>
        </tr>
      ))}
    </>
  )
}

function PatientStatusBadge({ patient }: { patient: Patient }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        patient.is_active === false
          ? 'bg-slate-100 text-slate-500'
          : 'bg-green-100 text-green-700'
      }`}
    >
      {patient.is_active === false ? 'Inativo' : 'Ativo'}
    </span>
  )
}

function PatientAllergyBadge({ count }: { count?: number | null }) {
  if (!count) return <span className="text-slate-400">Sem alerta</span>
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
      <ShieldAlert size={12} />
      {count} alergia{count !== 1 ? 's' : ''}
    </span>
  )
}

export default function PatientsPage() {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [patients, setPatients] = useState<Patient[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [count, setCount] = useState(0)

  const fetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestSeqRef = useRef(0)

  const fetchPatientsNow = useCallback(async (q: string) => {
    const seq = requestSeqRef.current + 1
    requestSeqRef.current = seq
    setLoading(true)
    setError(null)

    const params = new URLSearchParams({ ordering: 'full_name' })
    const trimmed = q.trim()
    if (trimmed) params.set('search', trimmed)

    try {
      const data = await apiFetch<PatientListResponse>(`/api/v1/patients/?${params.toString()}`)
      if (seq !== requestSeqRef.current) return
      setPatients(data.results ?? [])
      setCount(data.count ?? data.results?.length ?? 0)
    } catch (e) {
      if (seq !== requestSeqRef.current) return
      setPatients([])
      setCount(0)
      setError(e instanceof Error ? e.message : 'Não foi possível carregar pacientes.')
    } finally {
      if (seq === requestSeqRef.current) setLoading(false)
    }
  }, [])

  const fetchPatients = useCallback((q: string) => {
    if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current)
    fetchTimerRef.current = setTimeout(() => fetchPatientsNow(q), 300)
  }, [fetchPatientsNow])

  useEffect(() => {
    fetchPatientsNow('')
    return () => {
      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current)
    }
  }, [fetchPatientsNow])

  const summary = useMemo(() => summarizePatients(patients), [patients])
  const hasSearch = search.trim().length > 0

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Pacientes</h1>
          <p className="mt-1 text-sm text-slate-500">
            Cadastro, risco clínico e acesso rápido ao prontuário.
          </p>
        </div>
        <button
          onClick={() => router.push('/patients/new')}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <Plus size={16} />
          Novo paciente
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <Users size={14} />
            Total
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">{count}</p>
        </div>
        <div className="rounded-lg border border-green-200 bg-green-50 p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-green-700">
            <UserRound size={14} />
            Ativos na lista
          </div>
          <p className="mt-2 text-2xl font-bold text-green-700">{summary.active}</p>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-red-700">
            <ShieldAlert size={14} />
            Com alergia
          </div>
          <p className="mt-2 text-2xl font-bold text-red-700">{summary.withAllergies}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <FileText size={14} />
            Inativos
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-700">{summary.inactive}</p>
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <label htmlFor="patient-search" className="sr-only">
          Buscar paciente
        </label>
        <div className="flex items-center gap-3">
          <Search size={18} className="shrink-0 text-slate-400" />
          <input
            id="patient-search"
            type="text"
            placeholder="Buscar paciente, prontuário ou contato"
            className="min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:ring-0"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              fetchPatients(e.target.value)
            }}
          />
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Paciente', 'Prontuário', 'Nascimento', 'Contato', 'Risco', 'Status'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading ? (
                <PatientTableSkeleton />
              ) : patients.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <p className="font-medium text-slate-700">
                      {hasSearch ? 'Nenhum paciente encontrado.' : 'Nenhum paciente cadastrado ainda.'}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {hasSearch
                        ? 'Revise a busca ou limpe o filtro para ver todos os cadastros.'
                        : 'Cadastre o primeiro paciente para liberar prontuário, agenda e faturamento.'}
                    </p>
                    {!hasSearch && (
                      <button
                        onClick={() => router.push('/patients/new')}
                        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
                      >
                        <Plus size={16} />
                        Novo paciente
                      </button>
                    )}
                  </td>
                </tr>
              ) : patients.map((p) => (
                <tr
                  key={p.id}
                  className="cursor-pointer hover:bg-blue-50"
                  onClick={() => router.push(`/patients/${p.id}`)}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{p.full_name}</div>
                    {p.social_name && <div className="text-xs text-slate-500">Nome social: {p.social_name}</div>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{p.medical_record_number || '—'}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {p.birth_date ? new Date(p.birth_date + 'T00:00:00').toLocaleDateString('pt-BR') : '—'}
                    {p.age != null && <span className="ml-1 text-xs text-slate-400">({p.age}a)</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{p.phone || p.whatsapp || '—'}</td>
                  <td className="px-4 py-3">
                    <PatientAllergyBadge count={p.active_allergies_count} />
                  </td>
                  <td className="px-4 py-3">
                    <PatientStatusBadge patient={p} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="divide-y divide-slate-100 md:hidden">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="p-4">
                <div className="h-4 w-2/3 animate-pulse rounded bg-slate-100" />
                <div className="mt-2 h-3 w-1/2 animate-pulse rounded bg-slate-100" />
              </div>
            ))
          ) : patients.length === 0 ? (
            <div className="p-6 text-center">
              <p className="font-medium text-slate-700">
                {hasSearch ? 'Nenhum paciente encontrado.' : 'Nenhum paciente cadastrado ainda.'}
              </p>
              <p className="mt-1 text-sm text-slate-500">
                {hasSearch ? 'Tente outro termo de busca.' : 'Cadastre o primeiro paciente para iniciar o fluxo clínico.'}
              </p>
            </div>
          ) : patients.map((p) => (
            <button
              key={p.id}
              onClick={() => router.push(`/patients/${p.id}`)}
              className="w-full p-4 text-left hover:bg-blue-50"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-900">{p.full_name}</p>
                  <p className="mt-1 font-mono text-xs text-slate-500">{p.medical_record_number || 'Sem prontuário'}</p>
                </div>
                <PatientStatusBadge patient={p} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{p.age != null ? `${p.age} anos` : 'Idade não informada'}</span>
                <span>·</span>
                <span className="inline-flex items-center gap-1">
                  <Phone size={12} />
                  {p.phone || p.whatsapp || 'Sem contato'}
                </span>
              </div>
              <div className="mt-3">
                <PatientAllergyBadge count={p.active_allergies_count} />
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
