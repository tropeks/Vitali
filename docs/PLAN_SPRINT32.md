# Sprint 32: Compliance Pack GA

> Pode rodar em paralelo com Sprints 30–31 (toca frontend/legal/assinatura, não os engines de wedge).

## Context (ler antes de começar)

- `docs/SECURITY.md`, `docs/LGPD_PATIENT_PII_ENCRYPTION.md`, `docs/ICP_BRASIL.md`
- `backend/apps/signatures/` (ICP-Brasil: chain validation, OCSP/CRL), `backend/apps/emr/` (encounter/prescription sign), `backend/apps/patient_portal/`
- Estado: PII encriptada at rest ✅; audit log ✅; assinatura ICP — primitiva A1 + chain prontos, **integração no fluxo de encounter/prescription pendente**; `ICP_BRASIL_CHECK_REVOCATION=False`; privacy policy/cookie consent frontend faltam; DPA/DPO são templates.

## Goal

Fechar os itens de compliance que faltam para uma clínica operar de verdade e assinar contrato: assinatura digital integrada ao fluxo clínico, LGPD visível ao paciente (privacy policy, consent, direitos), e os artefatos jurídicos (DPA/RIPD templates) prontos para preencher.

## Planned Scope

### S32-01: Integração ICP-Brasil no Fluxo Clínico

- Conectar a primitiva de assinatura (já pronta) ao ato de assinar `Encounter`/`ClinicalNote`/`Prescription`: ao assinar, gerar assinatura ICP-Brasil A1, gravar `signature_hash` + `is_icp_brasil`.
- Fail-open documentado: se trust store vazio → assina com `is_icp_brasil=False` + warning (comportamento atual da primitiva), nunca bloqueia atendimento.
- Testes: encounter assinado tem assinatura válida quando cert presente; degrada quando ausente.

### S32-02: Revocation Checking Ready para Prod

- Documentar e testar `ICP_BRASIL_CHECK_REVOCATION=True` (fail-closed) com reachability aos endpoints ITI; deixar como opção de produção documentada em `docs/ICP_BRASIL.md` (não ligar por default).
- Command `refresh_icp_truststore` validado (popular AC Raiz + intermediates do ITI).

### S32-03: Privacy Policy & Cookie Consent (Frontend)

- Página de política de privacidade (rota pública) + banner de cookie consent LGPD no frontend (Next.js), com registro de consentimento.
- Texto base em PT-BR (placeholder claramente marcado para revisão jurídica — não inventar cláusulas como se fossem aprovadas).

### S32-04: Patient Rights Surface (Portal)

- No `patient_portal`: paciente vê seus dados (já existe backend), exporta (JSON/PDF), e solicita correção/eliminação (gera tarefa auditável para o tenant tratar).
- Não automatizar a eliminação clínica (retenção legal 20 anos CFM) — registrar solicitação + base legal.

### S32-05: DPA / RIPD / DPO Artifacts

- Templates preenchíveis em `docs/`: `DPA_TEMPLATE.md` (contrato de processamento), `RIPD_TEMPLATE.md` (relatório de impacto), e um guia de designação de DPO.
- UI em `/configuracoes` para o tenant registrar DPO designado e status do DPA assinado (já existe `AIDPAStatus` para IA — estender o conceito para o DPA geral se necessário).

### S32-06: Compliance Readiness Checklist

- `docs/COMPLIANCE_CHECKLIST.md`: checklist GA de LGPD/CFM/ICP que o operador percorre antes de ligar um tenant em produção, com links para cada artefato/feature.

## Acceptance Criteria

- Assinar encounter/prescription gera assinatura ICP-Brasil quando cert presente; degrada com warning quando ausente; testes verdes.
- Revocation fail-closed testado e documentado (opt-in prod).
- Privacy policy + cookie consent no frontend, consentimento registrado; build limpo.
- Paciente exporta dados e abre solicitação de direitos pelo portal; solicitação é auditável.
- Templates DPA/RIPD/DPO presentes; UI registra DPO + status DPA.
- `docs/COMPLIANCE_CHECKLIST.md` completo.

## Verification Commands

```bash
cd backend && pytest apps/signatures apps/emr apps/patient_portal apps/core -q --reuse-db -k "sign or icp or consent or dpa or rights"
cd frontend && npx playwright test e2e/auth.spec.ts
cd frontend && npm run build
```

## Out of Scope

- Revisão jurídica real dos textos (responsabilidade do Romulo/advogado) — marcamos placeholders
- Certificação formal SBIS/CFM (processo longo, inicia durante o piloto)
- Hardware token A3
