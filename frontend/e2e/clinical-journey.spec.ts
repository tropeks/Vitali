/**
 * E2E: Clinical front-desk to encounter journey
 *
 * Covers the product-critical path:
 * admin creates a patient, creates today's appointment through the API,
 * checks the patient in from the waiting room, starts the appointment,
 * lands on the linked encounter, documents SOAP/vitals, signs it, and verifies
 * the patient timeline points back to the signed encounter.
 */

import { test, expect, type APIResponse, type Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

async function expectApiOk(response: APIResponse, label: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${label} failed (${response.status()}): ${await response.text()}`);
  }
}

function cpfCheckDigit(digits: number[], initialWeight: number): number {
  const sum = digits.reduce((total, digit, index) => total + digit * (initialWeight - index), 0);
  const remainder = sum % 11;
  return remainder < 2 ? 0 : 11 - remainder;
}

function generateValidCpf(seed: number): string {
  const base = String(seed).padStart(9, '0').slice(-9).split('').map(Number);
  const first = cpfCheckDigit(base, 10);
  const second = cpfCheckDigit([...base, first], 11);
  return [...base, first, second].join('');
}

async function loginAsAdmin(page: Page): Promise<string> {
  await page.goto('/login');
  await page.fill('input[name="email"]', ADMIN_EMAIL);
  await page.fill('input[name="password"]', ADMIN_PASSWORD);

  const loginResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/login'),
    { timeout: 20_000 },
  );
  await page.click('button[type="submit"]');
  const response = await loginResponse;
  if (!response.ok()) {
    throw new Error(`admin login failed (${response.status()}): ${await response.text()}`);
  }

  await expect
    .poll(
      async () =>
        (await page.context().cookies()).find((cookie) => cookie.name === 'access_token_js')
          ?.value ?? null,
      { timeout: 20_000, message: 'admin login should set access_token_js' },
    )
    .not.toBeNull();

  const cookies = await page.context().cookies();
  const accessToken = cookies.find((cookie) => cookie.name === 'access_token_js')?.value;
  expect(accessToken, 'admin login should set access_token_js').toBeTruthy();
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
  return accessToken!;
}

test.describe('Clinical journey', () => {
  test('patient registration to signed encounter and timeline', async ({ page, request }) => {
    test.setTimeout(180_000);

    const timestamp = Date.now();
    const patientName = `Paciente Jornada ${timestamp}`;
    const patientCpf = generateValidCpf(timestamp);
    const doctorName = `Dra. Jornada ${timestamp}`;
    const doctorEmail = `dra.jornada+${timestamp}@vitali.com`;
    const access = await loginAsAdmin(page);

    const doctorResp = await request.post('/api/v1/hr/employees/', {
      headers: { Authorization: `Bearer ${access}` },
      data: {
        full_name: doctorName,
        email: doctorEmail,
        cpf: '12345678901',
        phone: '+5511999999999',
        role: 'medico',
        hire_date: '2026-01-01',
        contract_type: 'clt',
        employment_status: 'active',
        council_type: 'CRM',
        council_number: String(timestamp).slice(-6),
        council_state: 'SP',
        specialty: 'Clínica Médica',
        auth_mode: 'random_password',
        password: 'GeneratedPass123!',
        setup_whatsapp: false,
      },
    });
    await expectApiOk(doctorResp, 'create clinical professional');
    const { professional_id: professionalId } = await doctorResp.json();
    expect(professionalId).toBeTruthy();

    await page.goto('/patients/new');
    await page.fill('input[name="full_name"]', patientName);
    await page.fill('input[name="cpf"]', patientCpf);
    await page.fill('input[name="birth_date"]', '1990-05-15');
    await page.selectOption('select[name="gender"]', 'F');
    await page.fill('input[name="phone"]', '+5511988887777');
    await page.fill('input[name="email"]', `paciente.jornada+${timestamp}@vitali.com`);
    await Promise.all([
      page.waitForURL(/\/patients\/(?!new(?:[?#]|$))[^/?#]+$/, { timeout: 30_000 }),
      page.click('button:has-text("Cadastrar paciente")'),
    ]);
    await expect(page.getByRole('heading', { name: patientName })).toBeVisible();
    const patientId = page.url().split('/patients/')[1].split(/[?#]/)[0];
    expect(patientId).toBeTruthy();

    const start = new Date(Date.now() + 15 * 60 * 1000);
    start.setSeconds(0, 0);
    const end = new Date(start.getTime() + 30 * 60 * 1000);
    const appointmentResp = await request.post('/api/v1/appointments/', {
      headers: { Authorization: `Bearer ${access}` },
      data: {
        patient: patientId,
        professional: professionalId,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        type: 'consultation',
        source: 'receptionist',
        notes: 'Dor abdominal e náusea há dois dias.',
      },
    });
    await expectApiOk(appointmentResp, 'create appointment');

    await page.goto('/waiting-room');
    const waitingRow = page.locator('table tbody tr', { hasText: patientName }).first();
    await expect(waitingRow).toBeVisible({ timeout: 15_000 });
    await waitingRow.getByRole('button', { name: /Chegou/ }).click();
    await expect(waitingRow.getByText('Aguardando')).toBeVisible({ timeout: 10_000 });

    await Promise.all([
      page.waitForURL(/\/encounters\/[^/]+$/, { timeout: 90_000 }),
      waitingRow.getByRole('button', { name: /Chamar/ }).click(),
    ]);
    const encounterId = page.url().split('/encounters/')[1].split(/[?#]/)[0];
    expect(encounterId).toBeTruthy();
    await expect(page.getByRole('heading', { name: patientName })).toBeVisible();

    await page.getByTestId('vitals-weight_kg').fill('70');
    await page.getByTestId('vitals-height_cm').fill('168');
    await page.getByTestId('vitals-heart_rate').fill('76');
    await page.getByRole('button', { name: 'Salvar' }).first().click();

    await page.getByTestId('soap-subjective').fill('Paciente relata dor abdominal em cólica há dois dias.');
    await page.getByTestId('soap-objective').fill('Bom estado geral, hidratada, abdome doloroso à palpação profunda.');
    await page.getByTestId('soap-assessment').fill('Quadro compatível com gastroenterite aguda sem sinais de alarme.');
    await page.getByTestId('soap-plan').fill('Hidratação oral, sintomáticos e retorno se febre ou piora clínica.');
    await expect(page.locator('text=Salvo')).toBeVisible({ timeout: 10_000 });

    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Assinar Consulta' }).click();
    await expect(page.locator('text=Assinada')).toBeVisible({ timeout: 15_000 });

    await page.goto(`/patients/${patientId}`);
    await page.getByRole('button', { name: 'Timeline' }).click();
    await expect(page.locator(`text=Consulta com ${doctorName}`)).toBeVisible({ timeout: 10_000 });
    await page.locator(`text=Consulta com ${doctorName}`).click();
    await expect(page).toHaveURL(new RegExp(`/encounters/${encounterId}`));
  });
});
