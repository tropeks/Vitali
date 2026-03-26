# HealthOS — Project Brief

> **Status:** Validado | **Data:** 2026-03-26 | **Autor:** Romulo + Claude (System Architect)

---

## 1. Visão do Produto

**HealthOS** é uma plataforma hospitalar SaaS multi-tenant que integra ERP + EMR + AI numa
solução única, acessível e profissional. O produto mira clínicas e hospitais particulares de
pequeno e médio porte que não podem pagar os big-players (Tasy, MV, TOTVS Saúde) mas
precisam de um sistema robusto, compliant e moderno.

**North Star:** Oferecer tudo que os big-players oferecem, a um preço que cabe no bolso de
hospitais e clínicas menores, com AI como diferencial competitivo — não apenas um "Tasy
mais barato", mas um "Tasy mais inteligente e acessível".

**Referência de UX:** Tasy (Philips/Rede D'Or) — frontend profissional, fluxos integrados,
experiência enterprise.

---

## 2. Problema

Clínicas e hospitais particulares de pequeno/médio porte enfrentam um dilema:

- **Big-players (Tasy, MV, TOTVS):** R$50-200k/mês de licença. Inacessível.
- **Open-source (OpenEMR, Bahmni):** Grátis mas cru — exige time técnico dedicado,
  UX deficiente, compliance brasileira inexistente out-of-box.
- **Soluções locais menores:** Funcionalidade limitada, sem AI, sem interoperabilidade,
  vendor lock-in com dados proprietários.

**Resultado:** Clínicas operam com planilhas, sistemas fragmentados, processos manuais de
faturamento TISS que geram glosas, e zero inteligência sobre seus dados.

---

## 3. Público-Alvo

### Primário
- Clínicas e hospitais particulares (10-200 leitos) que atendem convênio + particular
- Brasil como mercado inicial (compliance TISS/TUSS + LGPD)

### Secundário (expansão)
- Países emergentes com problemas similares (LATAM, África, Sudeste Asiático)
- Clínicas especializadas (oftalmologia, ortopedia, dermatologia)

### Personas Principais
| Persona | Dor Principal | Feature Chave |
|---------|--------------|---------------|
| Administrador/Dono | Faturamento com glosas, falta de visibilidade financeira | BI + Faturamento TISS |
| Médico | Tempo perdido com burocracia, risco de erro | AI Scribe + Safety Net (futuro) |
| Recepcionista | Agendamento caótico, no-shows | WhatsApp + Smart Scheduling |
| Farmacêutico | Controle manual de estoque | Farmácia/Estoque |
| Paciente | Dificuldade de agendamento | WhatsApp 24/7 |

---

## 4. Módulos — Estrutura Modular (Marketplace)

O modelo de negócio é **modular tipo marketplace**: cada cliente monta seu plano
escolhendo os módulos que precisa. Isso exige feature flags por tenant e billing
engine com planos compostos.

### MVP (Phase 1)
| Módulo | Descrição | Prioridade |
|--------|-----------|------------|
| **Core** | Cadastro pacientes, agenda, usuários, multi-tenant (incluso sempre) | P0 |
| **EMR** | Prontuário eletrônico, evolução clínica, prescrição | P0 |
| **Faturamento** | TISS/TUSS, guias XML, controle de glosas | P0 |
| **Farmácia/Estoque** | Medicamentos, materiais, dispensação, compras | P0 |
| **AI: WhatsApp** | Agendamento 24/7, lembretes, confirmação, pós-consulta | P0 |
| **AI: TUSS Auto** | Codificação TUSS automática por AI, redução de glosas | P0 |

### Phase 2
| Módulo | Descrição |
|--------|-----------|
| **BI/Analytics** | Dashboards embeddáveis, indicadores financeiros/operacionais/clínicos, AI insights |
| **DICOM/PACS** | Integração Orthanc + OHIF Viewer, recepção de imagens |
| **AI: Clinical Safety Net** | Verificação de prescrição (interações, doses, alergias) |
| **AI: Scribe** | Documentação clínica automatizada (SOAP), sugestão CID-10 |

### Phase 3 (Visão)
| Módulo | Descrição |
|--------|-----------|
| **Telemedicina** | Consultas remotas integradas |
| **Portal do Paciente** | Acesso a resultados, agendamento web, histórico |
| **Smart Scheduling** | Otimização de agenda com AI preditiva |
| **Triagem Inteligente** | Classificação de urgência via WhatsApp (Manchester) |
| **AI Farmácia** | Predição de demanda, alertas de validade |

---

## 5. AI Strategy

AI é o diferencial competitivo central — não um add-on. Estratégia técnica:

- **Motor:** LLMs via API (Claude API / OpenAI) — sem treinar modelos do zero
- **Custo:** Variável por chamada (tokens), repassável no pricing modular
- **Viabilidade solo dev:** Alta — integração via API, não ML engineering
- **Diferencial:** Clínicas menores ganham acesso a inteligência que só grandes redes têm

### AI Features no MVP
1. **WhatsApp Patient Engagement** — Chatbot inteligente para agendamento, lembretes,
   confirmações, pós-consulta. Reduz no-show em 20-40%.
2. **Codificação TUSS Automática** — AI sugere códigos TUSS baseado na descrição do
   procedimento, reduzindo glosas por erro de codificação.

---

## 6. Constraints

| Constraint | Impacto |
|-----------|---------|
| Solo dev + AI | Máxima alavancagem open-source, frameworks opinados, automação |
| VPS inicial → AWS futuro | Docker/containers desde dia 1, portabilidade obrigatória |
| Budget ~R$150-500/mês infra | VPS Hetzner/Contabo, serviços self-hosted |
| Multi-tenant robusto | Schema-per-tenant no PostgreSQL (LGPD exige isolamento) |
| Pricing modular | Feature flags system + billing engine desde a fundação |
| Alcance global futuro | i18n desde o início, FHIR como padrão de interoperabilidade |

---

## 7. Compliance Obrigatória

| Regulação | Escopo | Requisito Chave |
|-----------|--------|-----------------|
| **LGPD** | Dados pessoais/sensíveis | Consentimento, DPO, direito à exclusão, criptografia |
| **TISS/TUSS** | Faturamento convênios | RN 501/2022 ANS, guias XML, terminologia padronizada |
| **CFM** | Prontuário eletrônico | Resolução CFM 1.821/2007, assinatura digital, integridade |
| **ANVISA** | Farmácia | Controle de medicamentos controlados, rastreabilidade |

---

## 8. Métricas de Sucesso

### 3 meses (MVP)
- Sistema funcional com Core + EMR + Faturamento + Farmácia + WhatsApp + TUSS AI
- 1-3 clínicas piloto operando
- Zero downtime crítico

### 6 meses
- 10+ clínicas pagantes
- Redução mensurável de glosas nos clientes (meta: -30%)
- NPS > 8 dos usuários clínicos

### 12 meses
- BI e DICOM/PACS operacionais
- Expansão para segundo mercado (ex: Portugal, Angola)
- Break-even operacional

---

## 9. Open-Source Leverage Strategy

| Necessidade | Solução Open-Source | Uso |
|-------------|-------------------|-----|
| DICOM Server (Phase 2) | Orthanc | Integrar como serviço Docker |
| DICOM Viewer (Phase 2) | OHIF Viewer | Embed como módulo frontend |
| BI/Dashboards (Phase 2) | Apache Superset | Embed dashboards por tenant |
| WhatsApp API | Evolution API | Self-hosted WhatsApp gateway |
| FHIR Interop | HAPI FHIR (referência) | Data models e API patterns |
| Data Models | OpenEMR/OpenMRS | Referência para schema design |

---

*Documento validado. Próximo: [ARCHITECTURE.md](./ARCHITECTURE.md)*
