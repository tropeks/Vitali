import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PatientDetailPage from './page'

const push = vi.fn()
const back = vi.fn()
const mockApiFetch = vi.fn()

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'patient-1' }),
  useRouter: () => ({ push, back }),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

function mockCommandCenterApi() {
  mockApiFetch.mockImplementation((path: string) => {
    if (path === '/api/v1/patients/patient-1/') {
      return Promise.resolve({
        id: 'patient-1',
        full_name: 'Ana Lima',
        social_name: 'Ana',
        medical_record_number: 'PAC-2026-00042',
        cpf_masked: '***.***.***-**',
        birth_date: '1990-01-01',
        age: 36,
        gender: 'F',
        gender_display: 'Feminino',
        blood_type: 'O+',
        phone: '(11) 99999-9999',
        whatsapp: '(11) 99999-9999',
        email: 'ana@example.com',
        is_active: true,
        allergies: [
          {
            id: 'allergy-1',
            substance: 'Penicilina',
            reaction: 'Anafilaxia',
            severity: 'life_threatening',
            severity_display: 'Risco de vida',
            status: 'active',
            status_display: 'Ativa',
          },
        ],
        medical_history: [
          {
            id: 'history-1',
            condition: 'Hipertensão arterial',
            cid10_code: 'I10',
            type: 'chronic',
            type_display: 'Crônica',
            status: 'active',
            status_display: 'Ativa',
          },
        ],
      })
    }
    if (path === '/api/v1/patients/patient-1/insurance/') {
      return Promise.resolve([
        {
          id: 7,
          provider_ans_code: '006246',
          provider_name: 'SulAmérica Saúde',
          card_number: 'CARD-123',
          valid_until: '2027-12-31',
          is_active: true,
        },
      ])
    }
    if (path === '/api/v1/patients/patient-1/timeline/') {
      return Promise.resolve({
        events: [
          {
            type: 'encounter',
            id: 'enc-1',
            date: '2026-05-07T10:00:00Z',
            status: 'open',
            professional: 'Dra. Carla',
            chief_complaint: 'Dor torácica',
          },
        ],
      })
    }
    if (path.startsWith('/api/v1/appointments/')) {
      return Promise.resolve([
        {
          id: 'appt-1',
          professional_name: 'Dra. Carla',
          start_time: '2026-05-08T13:00:00Z',
          status: 'confirmed',
          status_display: 'Confirmado',
        },
      ])
    }
    if (path.startsWith('/api/v1/encounters/')) {
      return Promise.resolve([
        {
          id: 'enc-1',
          professional_name: 'Dra. Carla',
          encounter_date: '2026-05-07T10:00:00Z',
          status: 'open',
          status_display: 'Em Aberto',
          chief_complaint: 'Dor torácica',
        },
      ])
    }
    if (path.startsWith('/api/v1/prescriptions/')) {
      return Promise.resolve([
        {
          id: 'rx-1',
          status: 'signed',
          status_display: 'Assinada',
          signed_at: '2026-05-07T11:00:00Z',
          prescriber_name: 'Dra. Carla',
          items: [{ id: 'item-1', drug_name: 'Dipirona', quantity: '1', unit_of_measure: 'ampola' }],
        },
      ])
    }
    if (path.startsWith('/api/v1/billing/guides/')) {
      return Promise.resolve({
        results: [
          {
            id: 'guide-1',
            guide_number: '202605000001',
            provider_name: 'SulAmérica Saúde',
            status: 'pending',
            status_display: 'Pendente',
            total_value: '150.00',
          },
        ],
      })
    }
    if (path.startsWith('/api/v1/problems/')) {
      return Promise.resolve([
        {
          id: 'prob-1',
          condition: 'Diabetes mellitus tipo 2',
          cid10_code: 'E11',
          cid_unmatched: false,
          clinical_status: 'active',
          clinical_status_display: 'Ativo',
          verification_status: 'confirmed',
          verification_status_display: 'Confirmado',
          onset_date: '2022-03-10',
          abatement_date: null,
        },
      ])
    }
    if (path.startsWith('/api/v1/immunizations/')) {
      return Promise.resolve([
        {
          id: 'imm-1',
          immunobiological: 'Influenza (gripe)',
          dose_number: 'dose única',
          lot: 'LOTE-2025',
          manufacturer: 'Butantan',
          date: '2025-04-01',
          pni_calendar_reference: 'PNI anual',
        },
      ])
    }
    if (path.startsWith('/api/v1/medication-reconciliations/')) {
      return Promise.resolve([
        {
          id: 'rec-1',
          encounter: 'enc-1',
          moment: 'admission',
          moment_display: 'Admissão',
          status: 'completed',
          status_display: 'Concluída',
          completed_at: '2026-05-07T11:00:00Z',
          created_at: '2026-05-07T10:00:00Z',
          items: [
            {
              id: 'reci-1',
              medication_name: 'Losartana 50mg',
              home_dosage: '1x ao dia',
              action: 'continue',
              action_display: 'Manter',
              reason: 'Controle pressórico estável',
            },
          ],
        },
      ])
    }
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

describe('PatientDetailPage', () => {
  it('renders the patient command center with risk, coverage, clinical and billing context', async () => {
    mockCommandCenterApi()

    render(<PatientDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Lima')).toBeInTheDocument()
    })

    expect(screen.getByText('Command Center do Paciente')).toBeInTheDocument()
    expect(screen.getAllByText('PAC-2026-00042').length).toBeGreaterThan(0)
    expect(screen.getByText('Risco crítico')).toBeInTheDocument()
    expect(screen.getAllByText('SulAmérica Saúde').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Em aberto').length).toBeGreaterThan(0)
    expect(screen.getByText('202605000001')).toBeInTheDocument()
    expect(screen.getByText('1 item(ns) prescritos')).toBeInTheDocument()
  })

  it('opens encounter rows without returning to the global list first', async () => {
    mockCommandCenterApi()
    const user = userEvent.setup()

    render(<PatientDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Fluxo operacional do paciente')).toBeInTheDocument()
    })

    await user.click(screen.getAllByRole('button', { name: /abrir consulta/i })[0])
    expect(push).toHaveBeenCalledWith('/encounters/enc-1')
  })

  it('surfaces governed problems (CID-10) and immunizations on the clinical tab, not just legacy history', async () => {
    mockCommandCenterApi()
    const user = userEvent.setup()

    render(<PatientDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Lima')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Clínico/ }))

    // Governed problem list (ProblemListItem), not the legacy medical_history field.
    await waitFor(() => {
      expect(screen.getByText('Diabetes mellitus tipo 2')).toBeInTheDocument()
    })
    expect(screen.getByText(/CID-10 E11/)).toBeInTheDocument()
    expect(screen.getByText('Lista de problemas (CID-10)')).toBeInTheDocument()

    // Governed immunization record.
    expect(screen.getByText('Influenza (gripe)')).toBeInTheDocument()

    // Legacy medical_history still visible but demoted to a secondary section.
    expect(screen.getByText('Histórico legado')).toBeInTheDocument()
    expect(screen.getAllByText('Hipertensão arterial').length).toBeGreaterThan(0)
  })

  it('surfaces medication reconciliation with per-transition decisions', async () => {
    mockCommandCenterApi()
    const user = userEvent.setup()

    render(<PatientDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Lima')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Reconciliação' }))

    await waitFor(() => {
      expect(screen.getByText('Losartana 50mg')).toBeInTheDocument()
    })
    expect(screen.getByText(/Reconciliação — Admissão/)).toBeInTheDocument()
    expect(screen.getByText('Concluída')).toBeInTheDocument()
    expect(screen.getByText('Manter')).toBeInTheDocument()
  })

  it('shows degraded module state without blocking the patient header', async () => {
    mockCommandCenterApi()
    mockApiFetch.mockImplementation((path: string) => {
      if (path === '/api/v1/patients/patient-1/') {
        return Promise.resolve({
          id: 'patient-1',
          full_name: 'Ana Lima',
          medical_record_number: 'PAC-2026-00042',
          birth_date: '1990-01-01',
          gender_display: 'Feminino',
          allergies: [],
          medical_history: [],
          is_active: true,
        })
      }
      if (path.includes('/billing/guides/')) {
        return Promise.reject(new Error('billing unavailable'))
      }
      if (path.includes('/timeline/')) return Promise.resolve({ events: [] })
      if (path.includes('/insurance/')) return Promise.resolve([])
      return Promise.resolve([])
    })

    render(<PatientDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Lima')).toBeInTheDocument()
    })

    expect(screen.getByText(/Dados parciais: faturamento indisponível/)).toBeInTheDocument()
  })
})
