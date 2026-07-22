'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { apiFetch } from '@/lib/api'

export interface PatientOption {
  id: string | number
  full_name: string
  medical_record_number?: string | null
  birth_date?: string | null
  cpf_masked?: string | null
}

type PatientPage = {
  results?: PatientOption[]
  next?: string | null
}

type Props = {
  value: PatientOption | null
  onChange: (patient: PatientOption | null) => void
  label?: string
  placeholder?: string
  required?: boolean
  disabled?: boolean
  id?: string
}

function apiPath(url: string) {
  if (url.startsWith('/')) return url
  const parsed = new URL(url)
  return `${parsed.pathname}${parsed.search}`
}

function secondaryLabel(patient: PatientOption) {
  return [patient.medical_record_number, patient.birth_date, patient.cpf_masked]
    .filter(Boolean)
    .join(' · ')
}

export default function PatientAutocomplete({
  value,
  onChange,
  label = 'Paciente',
  placeholder = 'Buscar por nome, CPF ou prontuário',
  required = false,
  disabled = false,
  id,
}: Props) {
  const generatedId = useId()
  const inputId = id ?? `patient-search-${generatedId}`
  const listId = `${inputId}-options`
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<PatientOption[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [activeIndex, setActiveIndex] = useState(-1)
  const requestId = useRef(0)

  useEffect(() => {
    if (value || query.trim().length < 2) {
      setOptions([])
      setNext(null)
      setError('')
      return
    }

    const currentRequest = ++requestId.current
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const params = new URLSearchParams({
          search: query.trim(),
          ordering: 'full_name',
          page_size: '20',
        })
        const data = await apiFetch<PatientPage | PatientOption[]>(`/api/v1/patients/?${params}`)
        if (currentRequest !== requestId.current) return
        setOptions(Array.isArray(data) ? data : (data.results ?? []))
        setNext(Array.isArray(data) ? null : (data.next ?? null))
        setActiveIndex(-1)
      } catch {
        if (currentRequest !== requestId.current) return
        setOptions([])
        setNext(null)
        setError('Não foi possível buscar pacientes.')
      } finally {
        if (currentRequest === requestId.current) setLoading(false)
      }
    }, 300)

    return () => window.clearTimeout(timer)
  }, [query, value])

  const select = (patient: PatientOption) => {
    onChange(patient)
    setQuery('')
    setOptions([])
    setNext(null)
  }

  const loadMore = async () => {
    if (!next || loadingMore) return
    setLoadingMore(true)
    try {
      const data = await apiFetch<PatientPage>(apiPath(next))
      setOptions((current) => {
        const known = new Set(current.map((patient) => String(patient.id)))
        return [...current, ...(data.results ?? []).filter((patient) => !known.has(String(patient.id)))]
      })
      setNext(data.next ?? null)
    } catch {
      setError('Não foi possível carregar mais pacientes.')
    } finally {
      setLoadingMore(false)
    }
  }

  const open = !value && query.trim().length >= 2 && (loading || error !== '' || options.length > 0)

  return (
    <div className="relative">
      <label htmlFor={inputId} className="mb-1 block text-xs font-semibold text-neu-inkSoft">
        {label}{required && <span aria-hidden="true"> *</span>}
      </label>
      {value ? (
        <div className="flex min-h-10 items-center justify-between gap-3 rounded-lg border border-neu-app bg-neu-input px-3 py-2">
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-neu-ink">{value.full_name}</span>
            {secondaryLabel(value) && <span className="block truncate text-xs text-neu-inkSoft">{secondaryLabel(value)}</span>}
          </span>
          <button
            type="button"
            aria-label={`Remover ${value.full_name}`}
            onClick={() => onChange(null)}
            disabled={disabled}
            className="rounded p-1 text-neu-inkMuted hover:text-neu-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neu-brand"
          >
            <X aria-hidden="true" size={16} />
          </button>
        </div>
      ) : (
        <div className="relative">
          <Search aria-hidden="true" size={16} className="absolute left-3 top-3 text-neu-inkMuted" />
          <input
            id={inputId}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={listId}
            aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
            autoComplete="off"
            disabled={disabled}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (!options.length) return
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActiveIndex((current) => Math.min(current + 1, options.length - 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActiveIndex((current) => Math.max(current - 1, 0))
              } else if (event.key === 'Enter' && activeIndex >= 0) {
                event.preventDefault()
                select(options[activeIndex])
              } else if (event.key === 'Escape') {
                setOptions([])
              }
            }}
            placeholder={placeholder}
            className="neu-input w-full py-2 pl-9 pr-9 text-sm"
          />
          {loading && <Loader2 aria-label="Buscando pacientes" size={16} className="absolute right-3 top-3 animate-spin text-neu-brand" />}
        </div>
      )}
      {open && (
        <div id={listId} role="listbox" className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-neu-app bg-neu-outer p-1 shadow-xl">
          {error ? (
            <p role="alert" className="px-3 py-2 text-sm text-red-700">{error}</p>
          ) : !loading && options.length === 0 ? (
            <p className="px-3 py-2 text-sm text-neu-inkSoft">Nenhum paciente encontrado.</p>
          ) : (
            <>
              {options.map((patient, index) => (
                <button
                  id={`${listId}-${index}`}
                  key={patient.id}
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => select(patient)}
                  className={`block w-full rounded-md px-3 py-2 text-left hover:bg-neu-panel ${index === activeIndex ? 'bg-neu-panel' : ''}`}
                >
                  <span className="block truncate text-sm font-semibold text-neu-ink">{patient.full_name}</span>
                  {secondaryLabel(patient) && <span className="block truncate text-xs text-neu-inkSoft">{secondaryLabel(patient)}</span>}
                </button>
              ))}
              {next && (
                <button type="button" onClick={loadMore} disabled={loadingMore} className="mt-1 w-full rounded-md px-3 py-2 text-sm font-semibold text-neu-brand hover:bg-neu-panel disabled:opacity-50">
                  {loadingMore ? 'Carregando…' : 'Carregar mais pacientes'}
                </button>
              )}
            </>
          )}
        </div>
      )}
      {!value && query.length === 1 && <p className="mt-1 text-xs text-neu-inkMuted">Digite pelo menos 2 caracteres.</p>}
    </div>
  )
}
