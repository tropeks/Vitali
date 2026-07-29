import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import TransfusaoTab from './TransfusaoTab'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const REQUEST = {
  id: 'req-1',
  patient: 'patient-1',
  component: 1,
  component_display: 'Concentrado de hemácias',
  quantidade: 1,
  urgencia: 'urgencia',
  indicacao: 'Anemia sintomática',
  status: 'liberada',
  crossmatches: [
    {
      id: 'cm-1',
      request: 'req-1',
      bag: 'bag-1',
      bag_identifier: 'DIN-0001',
      abo_compativel: true,
      rh_compativel: true,
      crossmatch_resultado: 'compativel',
      compativel: true,
    },
  ],
  created_at: '2026-07-25T10:00:00Z',
}

const ADMIN = {
  id: 'adm-1',
  request: 'req-1',
  patient: 'patient-1',
  bag_identifier: 'DIN-0002',
  status: 'concluida',
  started_at: '2026-07-25T12:00:00Z',
}

function routeApi(
  overrides: { requests?: any; administrations?: any; reactions?: any } = {},
) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/transfusion-requests/?patient=')) {
      return Promise.resolve(overrides.requests ?? [REQUEST])
    }
    if (url.startsWith('/api/v1/transfusion-administrations/')) {
      return Promise.resolve(overrides.administrations ?? [ADMIN])
    }
    if (url.startsWith('/api/v1/transfusion-reactions/')) {
      return Promise.resolve(overrides.reactions ?? [])
    }
    if (url === '/api/v1/blood-components/') return Promise.resolve([])
    if (url === '/api/v1/blood-bags/') return Promise.resolve([])
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TransfusaoTab', () => {
  it('gates the whole surface behind hemoterapia.read', () => {
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead={false}
        canWrite={false}
      />,
    )
    expect(screen.getByText('Sem acesso à hemoterapia')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('lists the patient requisições and administered transfusões', async () => {
    routeApi()
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite
      />,
    )

    await waitFor(() =>
      expect(screen.getAllByText('Concentrado de hemácias').length).toBeGreaterThan(0),
    )
    expect(screen.getByText('Urgência')).toBeInTheDocument()
    expect(screen.getByText('Liberada')).toBeInTheDocument()
    expect(screen.getByText('Compatível')).toBeInTheDocument()
    // administração joined to req-1 for its component + its own bag + status
    expect(screen.getByText('Bolsa DIN-0002')).toBeInTheDocument()
    expect(screen.getByText('Concluída')).toBeInTheDocument()
  })

  it('renders the reaction badge for an administração that has a reação', async () => {
    routeApi({
      reactions: [
        {
          id: 'rx-1',
          administration: 'adm-1',
          tipo: 'hemolitica_aguda',
          gravidade: 'grave',
          descricao: 'Hemólise aguda',
          notificado_hemovigilancia: true,
        },
      ],
    })
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite
      />,
    )

    await waitFor(() => expect(screen.getByText('Bolsa DIN-0002')).toBeInTheDocument())
    expect(screen.getByText(/Reação: Hemolítica aguda \(Grave\)/)).toBeInTheDocument()
    // With a reaction already present, no "Registrar reação" button.
    expect(screen.queryByRole('button', { name: 'Registrar reação' })).not.toBeInTheDocument()
  })

  it('opens the bedside checagem for a liberated requisição', async () => {
    routeApi()
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite
      />,
    )

    await waitFor(() =>
      expect(screen.getAllByText('Concentrado de hemácias').length).toBeGreaterThan(0),
    )
    fireEvent.click(screen.getByRole('button', { name: /Checagem beira-leito/ }))
    expect(
      screen.getByRole('dialog', { name: 'Checagem transfusional beira-leito' }),
    ).toBeInTheDocument()
  })

  it('opens the nova requisição form', async () => {
    routeApi()
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite
      />,
    )

    await waitFor(() =>
      expect(screen.getAllByText('Concentrado de hemácias').length).toBeGreaterThan(0),
    )
    fireEvent.click(screen.getByRole('button', { name: /Nova requisição/ }))
    expect(screen.getByRole('dialog', { name: 'Nova requisição transfusional' })).toBeInTheDocument()
  })

  it('opens the reação form for an administração without a reaction', async () => {
    routeApi()
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite
      />,
    )

    await waitFor(() => expect(screen.getByText('Bolsa DIN-0002')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Registrar reação' }))
    expect(
      screen.getByRole('dialog', { name: 'Registrar reação transfusional' }),
    ).toBeInTheDocument()
  })

  it('hides write actions when the user lacks hemoterapia.manage', async () => {
    routeApi()
    render(
      <TransfusaoTab
        patientId="patient-1"
        patientBarcode="MRN-001"
        encounterId="enc-1"
        canRead
        canWrite={false}
      />,
    )

    await waitFor(() =>
      expect(screen.getAllByText('Concentrado de hemácias').length).toBeGreaterThan(0),
    )
    expect(screen.queryByRole('button', { name: /Nova requisição/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Checagem beira-leito/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Registrar reação' })).not.toBeInTheDocument()
  })
})
