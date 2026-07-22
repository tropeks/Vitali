# Vitali — Avaliação de prontidão enterprise e roadmap de produto

**Data-base:** 22 de julho de 2026
**Status:** diagnóstico inicial para planejamento
**Escopo:** produto clínico, operação hospitalar, ERP, RH, financeiro, suprimentos, farmácia, portal, imagem, interoperabilidade, segurança e plataforma

## 1. Conclusão executiva

O Vitali já possui uma fundação relevante para uma operação ambulatorial: prontuário, agenda, atendimento, prescrição, laboratório, TISS, estoque/farmácia por lote, portal do paciente, imagens DICOM com visualizador, RBAC, MFA, auditoria e isolamento por schema.

Entretanto, **ainda não deve ser vendido ou operado como HIS/ERP hospitalar enterprise completo**. O código atual é melhor classificado como uma plataforma clínica ambulatorial funcional, com módulos hospitalares e administrativos em evolução.

Os bloqueadores mais importantes são:

1. **Segurança operacional:** `ENFORCE_TENANT_MEMBERSHIP` ainda é permissivo por padrão; administração de plataforma depende de superusuário; faltam segregação de funções (SoD), acesso privilegiado temporário e IAM corporativo.
2. **Continuidade:** produção é single-host/single-instance; backup documentado tem RPO de 24 h, sem PITR; PACS/OHIF não fazem parte do compose de produção.
3. **Operação hospitalar:** não há ADT/internação/leitos, SAE/eMAR, emergência completa, centro cirúrgico ou RIS com MWL/MPPS/Storage Commitment.
4. **ERP:** não há razão contábil, contas a pagar/receber, tesouraria, conciliação, fiscal, orçamento, custos, contratos, patrimônio ou engenharia clínica completos.
5. **HCM/RH:** existe somente um cadastro básico de funcionário; faltam estrutura organizacional, ponto, escalas trabalhistas, SST, benefícios, folha e eSocial.
6. **Dados e integração:** faltam MPI/EMPI, cadastro mestre corporativo, terminologia governada e um motor de integração HL7/FHIR/DICOM com monitoramento, reconciliação e replay.

O caminho recomendado não é criar telas isoladas por módulo. Primeiro deve ser construída uma **fundação transacional comum** — unidades, centros de custo, entidades legais, cadastros mestres, workflows de aprovação, eventos/outbox, documentos e ledgers imutáveis — sobre a qual os módulos clínicos e administrativos possam fechar seus ciclos.

## 2. Como esta avaliação foi feita

Foi realizada leitura do código, modelos, rotas, telas, configurações de deploy e documentação do repositório. A classificação indica presença e profundidade observáveis no projeto, não homologação regulatória nem validação operacional em ambiente hospitalar.

### Escala de maturidade

| Nível | Significado |
|---|---|
| M0 | Ausente |
| M1 | Modelo, primitiva técnica ou API inicial |
| M2 | Fluxo funcional parcial |
| M3 | Operacional para cenário ambulatorial controlado |
| M4 | Hospitalar/enterprise, resiliente, auditável e homologável |

### Prioridade

| Prioridade | Significado |
|---|---|
| P0 | Bloqueia produção com dado real ou segurança assistencial |
| P1 | Bloqueia oferta enterprise/hospitalar |
| P2 | Robustez, escala e eficiência operacional |
| P3 | Otimização, certificações e diferenciação |

## 3. Retrato atual

| Capacidade | Atual | Alvo | Síntese |
|---|---:|---:|---|
| Prontuário ambulatorial | M3 | M4 | Boa base; faltam longitudinalidade, governança clínica e reconciliação |
| Agenda e recepção | M3 | M4 | Fluxo útil; faltam recursos, multiunidade, capacidade e escala |
| Prescrição/CPOE | M2–M3 | M4 | Alertas e dispensação existem; ciclo hospitalar não está fechado |
| Laboratório/LIS | M2 | M4 | Pedido, resultado e portal existem; falta gestão completa da amostra e equipamentos |
| Imagem/RIS-PACS | M2 | M4 | DICOM/OHIF integrados no beta; falta RIS e operação enterprise |
| Portal do paciente | M2–M3 | M4 | Bom portal de leitura; falta autosserviço e gestão de dependentes |
| TISS/revenue cycle | M2–M3 | M4 | Núcleo forte; falta recebível, baixa e reconciliação ponta a ponta |
| Estoque/farmácia | M2–M3 | M4 | Lotes, FEFO e ledger existem; faltam WMS, inventário e escrituração regulatória |
| Compras | M1–M2 | M4 | Pedido e recebimento simples; falta sourcing, aprovação e three-way match |
| Financeiro/contábil/fiscal | M0–M1 | M4 | PIX pontual não constitui financeiro ou ERP |
| RH/HCM/folha | M1 | M4 | Cadastro básico; domínio trabalhista praticamente ausente |
| Internação/emergência/cirurgia | M0–M1 | M4 | Bloqueador para posicionamento hospitalar |
| IAM, segurança e auditoria | M2–M3 | M4 | Boas primitivas; faltam enforcement e controles enterprise |
| HA/DR/observabilidade | M1–M2 | M4 | Adequado a beta; inadequado a operação 24x7 |
| Integração e dados mestres | M1–M2 | M4 | Integrações pontuais; falta backbone corporativo |

## 4. Gaps clínicos e operacionais

### 4.1 Prontuário e governança clínica — P0/P1

**Existe:** paciente, alergias, antecedentes, profissionais, encontros, SOAP, sinais vitais, documentos, procedimentos, prescrições, assinatura/hash, auditoria e convênios do paciente.

**Falta:**

- lista de problemas longitudinal, diagnósticos e procedimentos com terminologias governadas;
- reconciliação medicamentosa, plano de cuidado e resumo clínico;
- formulários configuráveis, coassinatura e correção exclusivamente por adendo;
- consentimento granular, finalidade de uso e acesso emergencial `break-glass`;
- proveniência clínica e trilha imutável também para leitura/exportação;
- integração interoperável homologada com perfis nacionais aplicáveis.

**Aceite:** registro assinado não é sobrescrito; toda correção vira adendo; acesso excepcional exige motivo e alerta; importação/exportação preserva autoria, versão e proveniência.

### 4.2 Agenda, recepção e capacidade — P1

**Existe:** agenda semanal, disponibilidade, conflitos, sala de espera, check-in, waitlist e no-show.

**Falta:** recursos/salas/equipamentos, recorrência, multiunidade, agendas de exames e cirurgia, elegibilidade/autorização, fila/senha, overbooking governado, SLAs e planejamento de capacidade.

**Aceite:** busca remota com 100 mil pacientes em p95 menor que 500 ms, sem dropdown massivo; concorrência impede double-booking de profissional, sala e equipamento.

### 4.3 CPOE, enfermagem e eMAR — P0

**Existe:** prescrição, itens, alertas de alergia/interação/dose, overrides e dispensação relacionada; sinais vitais e NEWS2 básicos.

**Falta:** ordens unificadas de medicamento, laboratório, imagem, dieta e cuidado; order sets versionados; reconciliação; cálculo renal/hepático/pediátrico; diluição/infusão; validação farmacêutica; SAE; plano de cuidados; balanço hídrico; dispositivos; passagem de plantão; administração à beira-leito com código de barras, dupla checagem e eMAR.

**Aceite:** ciclo prescrição → validação → dispensação → cinco certos → administração fica íntegro e auditável; alertas e overrides são governados e clinicamente validados.

### 4.4 LIS/laboratório — P0/P1

**Existe:** catálogo, pedido, coleta, resultado, validação, faixas/componentes, microbiologia inicial, PDF assinado, portal e inbox idempotente. A integração documentada cobre ORU restrito e pressupõe gateway externo para transporte ASTM/MLLP.

**Falta:** accession e etiquetas, barcode, cadeia de custódia, alíquotas, bancadas/worklists, QC, calibração, reagentes, delta check, resultados críticos com closed loop, reflexo/repetição, antibiograma, patologia/genética, correção versionada e LOINC/UCUM governados; OML/ORM/ORU/ACK bidirecional e drivers por equipamento.

**Aceite:** amostra tem ID único e scan em todo handoff; mensagem tem ACK/retry/DLQ/replay; resultado crítico registra comunicação e confirmação; cada analisador passa por homologação bidirecional.

### 4.5 RIS, PACS e equipamentos de imagem — P0/P1

**Existe:** índice `DicomStudy`, UID/accession, vínculo fail-closed por paciente, sincronização/webhook Orthanc, visualizador white-label, laudo e acesso no portal.

**Falta:** pedido RIS, protocolos, agenda de modalidade, cadastro de AE/device, C-ECHO, MWL, MPPS, Storage Commitment, roteamento, quarentena/reconciliação, VNA/retenção, priors, laudo estruturado/voz, dose/radioproteção, QA de displays e HA/DR DICOM.

**Aceite:** ordem gera accession e MWL; modalidade publica MPPS; estudo só conclui após commitment; divergência vai para quarentena; priors e laudo assinado abrem no viewer; restauração completa DB↔PACS é testada.

### 4.6 Internação, emergência e centro cirúrgico — P0/P1

**Internação/leitos (M0):** implementar ADT, episódio, unidade/quarto/leito, reserva, transferência, isolamento, ocupação, censo, rounds, alta, sumário, hotelaria e conta diária.

**Emergência (M1):** evoluir triagem/NEWS2 para chegada sem agendamento, classificação institucional validada, fila por gravidade/tempo, reavaliação, protocolos tempo-dependentes, observação, transferência e internação.

**Centro cirúrgico (M0):** mapa cirúrgico, sala/equipe, autorização, checklist, anestesia, materiais/OPME/consignado, lote/UDI, implantes, tempos, RPA e fechamento da conta.

**Aceite hospitalar mínimo:** ADT completo e mapa de leitos consistente sob concorrência; emergência prioriza gravidade e SLA; cirurgia rastreia checklist, equipe, implante, lote e consumo por paciente.

### 4.7 Telemedicina — P1

O modelo atual possui lifecycle e sala, mas declara não fornecer WebRTC/TURN/STUN, SFU ou gravação segura. Para uma oferta real faltam vídeo, sala virtual, consentimento, verificação de dispositivo/rede, chat/anexos, acompanhante, fallback, retenção e métricas de QoS.

### 4.8 Portal do paciente — P0/P1

**Existe:** convite, ativação/revogação, perfil, consultas, encontros, receitas, alergias, laboratório, imagens/laudos, viewer e exportação/pedido LGPD.

**Falta:** agendar/remarcar/cancelar, check-in e formulários, dependentes/procuradores, consentimentos, mensagens, pagamentos, upload, notificações/preferências, correções cadastrais aprovadas, acessibilidade WCAG 2.2 AA, MFA/passkey e recuperação robusta de conta.

**Aceite:** paciente controla o ciclo sem intervenção da recepção; representação de dependente tem escopo e validade; sessões, IDOR e isolamento multi-tenant têm testes automatizados.

## 5. ERP, financeiro e revenue cycle

### 5.1 Financeiro e tesouraria — P0/P1

**Existe:** cobrança PIX pontual ligada a consulta e webhook Asaas.

**Falta:** contas a receber/pagar, baixas parciais, caixa/bancos, conciliação, cartão/boleto/CNAB, cobrança e estorno, inadimplência, fluxo de caixa, centros de custo e orçamento.

**Aceite:** atendimento e compra originam títulos; baixas/webhooks são idempotentes; extrato é conciliado; fechamento impede alteração retroativa e toda reabertura exige aprovação.

### 5.2 Contabilidade, controladoria e custos — P1/P2

Implementar plano de contas, partidas dobradas, diário/razão, balancete, DRE, balanço, competência, rateios, orçamento versus realizado e custo por paciente/procedimento.

**Aceite:** todo evento econômico gera lançamento balanceado; período fechado fica travado; razão, subledgers e relatórios reconciliam sem ajuste manual oculto.

### 5.3 Fiscal — P1/P2

Implementar cadastro fiscal, NFS-e/NF-e conforme aplicabilidade, documentos de entrada, XML/protocolos, retenções, cancelamentos e obrigações acessórias aplicáveis. Regras tributárias devem ser versionadas e integrações municipais/estaduais isoladas por adaptadores.

### 5.4 Convênios/TISS e particular — P0/P1

**Existe:** operadoras, tabelas/vigência, autorização, guias, itens TUSS, lotes/XML, retorno, glosa, recurso e alertas.

**Falta:** elegibilidade online, demais guias conforme escopo, anexos, ciclo completo de autorização, SLA de lote/recurso, repasse médico, recebível, baixa, conciliação e contratos ricos por operadora.

**Aceite:** encounter → guia → lote → protocolo → retorno → glosa/recurso → recebível → baixa é um único ciclo reconciliável.

### 5.5 SUS — P1 se fizer parte do mercado-alvo

Não foram encontrados BPA, APAC, AIH, SIA/SIH ou faturamento por competência. Requer CNES, SIGTAP versionado, CBO, críticas, autorização e exportação/retorno DATASUS. Se a estratégia inicial for exclusivamente privada, manter como P2 explícito, não como capacidade implícita.

## 6. Suprimentos, estoque, farmácia e ativos

### 6.1 Compras e fornecedores — P0/P1

**Existe:** fornecedor, pedido, itens e recebimento parcial/total que cria lote e movimento.

**Falta:** requisição, cotação multi-fornecedor, mapa comparativo, alçadas, contratos, catálogo, condições, frete/impostos, nota de entrada, devolução, homologação e three-way match entre pedido, recebimento e nota.

**Aceite:** solicitante não aprova o próprio pedido; alçada considera valor e centro de custo; divergência exige override justificado; recebimentos e devoluções são rastreáveis.

### 6.2 Estoque geral/WMS — P0

**Existe:** medicamento/material, saldo por lote/local/validade, movimentos append-only, bloqueio de saldo negativo, FEFO e alertas.

**Falta:** almoxarifados e endereçamento, reserva, quarentena, inventário/cíclico e contagem cega, conversões de unidade/embalagem, valorização, kits, OPME/consignado, série/UDI, requisição interna, transferência em trânsito com aceite, recall, cadeia fria e barcode.

**Aceite:** ledger reconcilia saldo físico; transferência possui saída e entrada; quarentena impede dispensação; ajuste de inventário requer aprovação; recall localiza pacientes e destinos afetados.

### 6.3 Medicamentos controlados — P0

**Existe:** classes A/B/C, permissão específica, receita assinada, lote/FEFO, justificativa e alertas comportamentais.

**Falta:** livro/escrituração regulatória por substância e apresentação, regras versionadas de receituário, numeração/validade/limites, retenção, inventário regulatório, perdas e quebras com dupla conferência, responsável técnico, exportação regulatória quando aplicável, recall e temperatura.

**Aceite:** nenhuma movimentação sem documento, prescritor, dispensador e lote; correção só por contramovimento; fechamento é assinado; perda/divergência exige dupla aprovação.

### 6.4 Contratos, patrimônio e engenharia clínica — P1

Criar contratos de fornecedor, operadora, prestador, locação e manutenção com versões, reajustes, SLAs, teto e alertas. Criar ativos com tombamento, serial/UDI, localização, custódia, depreciação, calibração, preventiva/corretiva, OS, peças, garantia, indisponibilidade e descarte.

**Aceite:** ativo crítico vencido gera bloqueio/alerta conforme política; preventiva cria OS; downtime e custo total são mensuráveis; pedido/tabela usa contrato vigente.

## 7. RH, força de trabalho e folha

### 7.1 Cadastro mestre de pessoas — P1

**Existe:** funcionário vinculado ao usuário, admissão, status, contrato e desligamento lógico.

**Falta:** matrícula, pessoa, documentos, dependentes, dados bancários, cargo/CBO, lotação, gestor, centro de custo, histórico contratual/salarial, benefícios, férias/licenças e vencimentos. Há divergências atuais entre enums de status/contrato no backend e frontend que devem ser normalizadas.

### 7.2 Escalas, ponto e dimensionamento — P1

`ScheduleConfig` clínico não equivale à jornada trabalhista. Implementar jornadas, marcações imutáveis, origem/dispositivo, banco de horas, extras/adicionais, justificativas, aprovações, espelho, plantões, trocas, cobertura, descanso e dimensionamento.

### 7.3 SST/saúde ocupacional — P1/P2

Implementar ASO e exames admissionais/periódicos/demissionais, PGR/PCMSO, matriz cargo-risco, EPI, treinamentos, CAT, afastamentos e alertas de vencimento, com acesso médico ocupacional segregado do RH.

### 7.4 Folha e eSocial — P1/P2

Recomendação: inicialmente integrar um provedor/contabilidade, mantendo no Vitali uma camada de eventos, validação, prévia, aprovação, recibos e reconciliação — em vez de criar imediatamente um motor legal próprio.

Cobrir variáveis, proventos/descontos, encargos, férias, 13º, rescisão, retroativos, holerite, contabilização/pagamento e eventos eSocial aplicáveis.

**Aceite:** eventos vêm de RH/ponto aprovados; fechamento/reabertura tem alçada; recibos são preservados; total da folha reconcilia com financeiro e contabilidade.

## 8. Fundação enterprise transversal

### 8.1 Cadastros e componentes comuns — P0

Antes dos novos módulos, criar:

- `LegalEntity`, estabelecimento, unidade, setor, sala, leito, centro de custo e recurso;
- `Party` para fornecedor, operadora, colaborador e prestador;
- MPI/EMPI com CPF/CNS/MRN/issuer, fila de duplicatas e merge/unmerge auditável;
- serviço de terminologia e versionamento para CID, CIAP, LOINC, UCUM, TUSS/CBHPM, medicamentos e demais vocabulários licenciados/aplicáveis;
- `ApprovalWorkflow`, etapas, alçadas, delegações e matriz de conflitos;
- documentos/anexos, numeração transacional, moeda/dinheiro e período fiscal;
- eventos de domínio, outbox/inbox duráveis, idempotência e DLQ/replay;
- ledgers separados: quantidade de estoque, valorização e contabilidade.

Todo registro econômico, assistencial ou operacional deve carregar os escopos necessários de tenant, entidade legal, estabelecimento, unidade e centro de custo.

### 8.2 IAM, RBAC, SoD e privilégio — P0/P1

- falhar o boot de produção se membership por tenant não estiver enforced;
- substituir superusuário cotidiano por `platform_operator` explícito e acesso JIT;
- adicionar OIDC/SAML corporativo, SCIM/JIT provisioning e MFA resistente a phishing para privilegiados;
- escopo por unidade, equipe, turno, relação assistencial e finalidade de uso;
- maker-checker para pagamento, controlados, ajustes, exportação e configuração DICOM;
- break-glass com justificativa, tempo limitado, alerta e revisão.

Corrigir também a autorização das configurações de privacidade: a leitura hoje exige apenas autenticação e a escrita usa `IsAdminUser`/`is_staff`, em vez de permissões tenant-scoped. Criar `privacy.read` e `privacy.manage`, papel DPO e auditoria before/after.

### 8.3 Auditoria, privacidade e compliance — P0/P1

Evoluir o `AuditLog` para cobertura automática de leitura, escrita, exportação, autenticação e configuração; correlation ID; exportação WORM ou hash chaining; retenção/legal hold; envio a SIEM e alertas de acesso anômalo.

Fechar inventário/ROPA, base legal/finalidade, comprovantes de consentimento versionados, DSAR, retenção, aviso de privacidade, RIPD, contato do DPO e workflow de incidente. Certificação deve ser tratada como trilha separada de evidências, nunca presumida pelo código.

### 8.4 Integração e API management — P0/P1

Criar gateway tenant-scoped com HL7 v2 ADT/ORM/ORU, ACK/retry/DLQ/replay; FHIR de leitura e escrita com perfis, versionamento, ETag, consentimento e provenance; DICOM/RIS; credenciais rotativas, mTLS/OAuth client credentials, quotas, catálogo OpenAPI, webhooks assinados e console operacional.

### 8.5 Alta disponibilidade, DR e observabilidade — P0

O alvo mínimo deve incluir PostgreSQL com PITR e failover testado, aplicações redundantes atrás de balanceador, storage DICOM e mídia duráveis, backups imutáveis fora da conta/host e restauração coordenada de banco, mídia, PACS, certificados e configurações.

RPO/RTO devem ser definidos por jornada clínica e contrato. Para o core clínico, usar como ponto de partida RPO ≤ 15 min e RTO ≤ 60 min, sujeito à validação de negócio.

Produção deve exigir logs estruturados, métricas e traces com remoção de PHI, SLOs, burn-rate alerts, monitoramento de filas/banco/storage/certificados, plantão e revisão pós-incidente.

A topologia de proxies deve ser explícita por ambiente. A configuração atual assume um proxy, enquanto o beta usa Cloudflare Tunnel mais nginx. Bloquear acesso direto ao origin e testar spoofing de `X-Forwarded-For`, rate limit e registro correto do IP do cliente.

### 8.6 AppSec e supply chain — P1/P2

Adicionar SAST, SCA, secret scanning, scan de containers, SBOM, assinatura/proveniência de imagem, política de licenças, DAST e SLA de dependências. Deploy deve aceitar apenas artefato assinado e migrations compatíveis por estratégia expand/contract.

## 9. Menus e papéis recomendados

### Menus por domínio

- **Assistencial:** Agenda, Recepção, Emergência, Internação/Leitos, Enfermagem, CPOE, Cirurgia, Laboratório, Imagem, Farmácia clínica.
- **Faturamento:** Autorizações, Guias, Lotes, Retornos, Glosas/Recursos, Particular, SUS, Repasse médico, Contratos/Tabelas.
- **Financeiro:** Receber, Pagar, Caixa/Bancos, Conciliação, Cobrança, Orçamento, Centros de custo, Fechamentos.
- **Suprimentos:** Requisições, Cotações, Pedidos, Recebimentos, Fornecedores, Contratos, Notas de entrada.
- **Estoque e Farmácia:** Almoxarifados, Saldos/Lotes, Inventários, Transferências, Quarentena/Recall, Dispensação, Controlados.
- **Pessoas:** Funcionários, Estrutura/Cargos, Escalas, Ponto, Férias/Afastamentos, Benefícios, SST, Folha, eSocial, Portal do colaborador.
- **Controladoria/Fiscal:** Plano de contas, Lançamentos, Rateios, Custos, Demonstrativos, Documentos fiscais e Obrigações.
- **Patrimônio/Engenharia clínica:** Ativos, OS, Preventivas, Calibrações, Contratos, Peças e Indicadores.
- **Administração hospitalar:** Identidade/Acessos, Aprovações, Privacidade, Auditoria, Unidades/Setores, Cadastros mestres, Integrações, Modalidades/PACS, Continuidade e Mudanças.
- **Control Plane Vitali:** Tenants/Ambientes, Entitlements, Quotas, Fleet health, Versões/Rollouts, SLO/Incidentes, Support JIT, Residency e Metering.

### Papéis mínimos

`tenant_owner`, `identity_admin`, `security_admin`, `privacy_officer`, `auditor_readonly`, `infra_admin`, `pacs_admin`, `integration_admin`, `biomedical_engineer`, `clinical_informatics_admin`, `master_data_steward`, `backup_operator`, `incident_commander`, `change_manager`, `billing_admin`, `treasury_maker`, `treasury_approver`, `controlled_stock_custodian`, `payroll_admin`, `platform_operator_jit` e `support_engineer_jit`.

Conflitos mínimos: solicitante ≠ aprovador; criador de fornecedor ≠ pagador; treasury maker ≠ checker; custodiante de controlados ≠ aprovador de ajuste; identity admin ≠ auditor; suporte/plataforma sem acesso clínico salvo break-glass.

## 10. Roadmap recomendado

### Progresso da Onda 0

Primeira fatia implementada em 22 de julho de 2026:

- [x] System-check de produção para impedir `ENFORCE_TENANT_MEMBERSHIP=False` validado.
- [x] Privacidade separada em `privacy.read` e `privacy.manage`, tenant-scoped e sem bypass por `is_staff`.
- [x] Fundação organizacional inicial: entidade legal, estabelecimento, unidade organizacional e centro de custo, com hierarquias validadas e RBAC.
- [x] Orthanc e visualizador incluídos de forma reproduzível no compose de produção, com volume e healthchecks.
- [x] Backup consistente e restore drill não destrutivo do arquivo de imagens.
- [ ] Executar backfill e ligar o enforcement no ambiente de staging/produção.
- [x] MPI inicial com identificadores cifrados, digest HMAC e fila humana de duplicidades, sem merge automático.
- [x] Workflow/alçadas sequenciais, maker-checker, auditoria e outbox transacional imutável.
- [x] Overlay opt-in de PITR com WAL archive, base backup verificado e restore drill descartável.
- [x] Redis segregado por cache, broker e resultados, com ACLs, persistência e perfil de evolução distribuída.
- [x] RabbitMQ/Celery opt-in com filas por criticidade, entrega durável e checks de configuração.
- [x] Observabilidade opt-in com Prometheus, Grafana, OTel, exporters, SLOs e alertas iniciais.
- [ ] Terminologia governada e inbox/replay de integrações.
- [ ] Ativar e comprovar PITR em janela; completar HA e restauração coordenada full-stack.
- [ ] Auditoria/SIEM e baseline LGPD operacional completos.
- [ ] WMS/controlados e financeiro mínimo reconciliável.

Fatia operacional seguinte implementada localmente em 22 de julho de 2026:

- [x] Console administrativo para organização, MPI e aprovações.
- [x] Inbox de integrações com idempotência, retry, dead-letter e replay operacional.
- [x] Dispatcher transacional da outbox com execução tenant-aware.
- [x] Almoxarifados, endereçamento, quarentena e recall rastreável.
- [x] Inventário cego com ajuste somente após maker-checker.
- [x] Transferência entre almoxarifados com ledger de saída e entrada.
- [x] CD corrigido para migrar schemas compartilhados e de tenants.
- [ ] Financeiro mínimo reconciliável e escrituração regulatória completa de controlados.

### Onda 0 — tornar a fundação segura (P0)

1. Enforce de tenant e hardening de administração privilegiada.
2. Cadastro organizacional, MPI/EMPI, terminologia e workflows/alçadas.
3. HA/PITR, backup full-stack, PACS reproduzível em produção e restore drill.
4. Auditoria/SIEM, LGPD operacional, outbox/inbox e idempotência.
5. Estoque: inventário, quarentena, transferência, recall e controlados.
6. Financeiro mínimo: AR/AP, conciliação e fechamento do TISS até a baixa.

### Onda 1 — fechar os ciclos críticos

Primeira fatia vertical implementada em 22 de julho de 2026:

- [x] CPOE reutilizando prescrição assinada, validação farmacêutica e eMAR transacional com dupla checagem de controlados.
- [x] SAE estruturada e imutável após assinatura.
- [x] LIS com cadastro de analisadores, cadeia de custódia por barcode e reconhecimento fechado de resultados críticos.
- [x] RIS com modalidades, estado C-ECHO, MWL, MPPS e Storage Commitment idempotentes.
- [x] RH operacional com jornada, ponto imutável/idempotente e SST/ASO auditável.
- [ ] Compras completas, contratos e three-way match.
- [ ] Portal transacional, dependentes, pagamentos e consentimentos.
- [ ] Interfaces operacionais completas e validação clínica/assistencial dos fluxos desta fatia.

1. CPOE/eMAR/SAE e validação farmacêutica.
2. LIS com rastreio de amostra, críticos e equipamentos bidirecionais.
3. RIS com modalidades, C-ECHO, MWL, MPPS e Storage Commitment.
4. Compras completas, contratos e three-way match.
5. RH mestre, ponto, escala e SST.
6. Portal transacional, dependentes, pagamentos e consentimentos.

### Onda 2 — habilitar hospital e ERP

1. ADT, internação, leitos, alta e conta hospitalar.
2. Emergência completa e protocolos tempo-dependentes.
3. Contabilidade, controladoria, fiscal e custos assistenciais.
4. Folha/eSocial por integração, repasse médico e portal do colaborador.
5. Patrimônio, manutenção e engenharia clínica.
6. Interoperabilidade HL7/FHIR e API management corporativo.

### Onda 3 — ampliar escopo e escala

1. Centro cirúrgico, anestesia, RPA, OPME e implantes.
2. SUS, se confirmado no mercado-alvo.
3. Telemedicina real com vídeo e contingência.
4. Control plane de frota, residência de dados e rollout canário.
5. Certificações, FinOps, governança de dados, load/soak/chaos tests.

## 11. Epics iniciais para abrir backlog

| ID | Epic | Pri | Depende de |
|---|---|---:|---|
| ENT-001 | Enforcement multi-tenant e plataforma JIT | P0 | — |
| ENT-002 | Modelo organizacional e centros de custo | P0 | ENT-001 |
| ENT-003 | MPI/EMPI e identidade do paciente | P0 | ENT-002 |
| ENT-004 | Terminologia e cadastros mestres | P0 | ENT-002 |
| ENT-005 | Workflow, alçadas, SoD e documentos | P0 | ENT-001/002 |
| ENT-006 | Outbox/inbox, integração e reconciliação | P0 | ENT-001 |
| ENT-007 | HA, PITR e DR full-stack | P0 | — |
| ENT-008 | WMS, inventário, quarentena e recall | P0 | ENT-002/005 |
| ENT-009 | Escrituração de controlados | P0 | ENT-005/008 |
| ENT-010 | AR/AP, tesouraria e conciliação | P0 | ENT-002/005 |
| ENT-011 | Revenue cycle TISS ponta a ponta | P0 | ENT-010 |
| ENT-012 | CPOE, validação e eMAR | P0 | ENT-003/004/006 |
| ENT-013 | LIS enterprise | P0/P1 | ENT-003/004/006/008 |
| ENT-014 | RIS/PACS enterprise | P0/P1 | ENT-003/006/007 |
| ENT-015 | Portal transacional e representantes | P1 | ENT-003/005/010 |
| ENT-016 | Compras, contratos e three-way match | P1 | ENT-005/008/010 |
| ENT-017 | RH mestre, escala, ponto e SST | P1 | ENT-002/005 |
| ENT-018 | ADT, internação e leitos | P1 | ENT-002/003/012 |
| ENT-019 | Emergência | P1 | ENT-018/012 |
| ENT-020 | Contabilidade, fiscal e custos | P1/P2 | ENT-010/016/017 |
| ENT-021 | Folha/eSocial integrada | P1/P2 | ENT-017/020 |
| ENT-022 | Patrimônio e engenharia clínica | P1 | ENT-002/016 |
| ENT-023 | Centro cirúrgico e OPME | P1/P2 | ENT-012/018/008 |
| ENT-024 | IAM corporativo, SIEM e AppSec | P1 | ENT-001/005 |
| ENT-025 | Control plane e gestão de frota | P2 | ENT-007/024 |

## 12. Definition of Enterprise Ready

Um módulo só pode ser marcado como enterprise quando:

- possui owner de produto e owner operacional;
- aplica tenant, unidade e escopo de acesso no backend;
- tem SoD, alçadas e break-glass quando aplicável;
- registra autoria, before/after, motivo e correlation ID;
- usa idempotência e reconciliação para integrações e dinheiro;
- suporta concorrência, volume e indisponibilidade de dependências;
- tem SLO, métricas, alertas, runbook e responsável de plantão;
- possui backup/restauração testados conforme seu RPO/RTO;
- tem testes unitários, integração, E2E, segurança, carga e isolamento;
- oferece exportação e retenção coerentes com LGPD e regras aplicáveis;
- foi validado pelo responsável clínico, contábil, fiscal ou regulatório do domínio;
- tem documentação de implantação, atualização, rollback e contingência.

## 13. Decisões de produto que precisam ser tomadas

1. O mercado inicial será clínica privada, hospital privado, hospital misto/SUS ou uma sequência explícita desses segmentos?
2. Quais módulos serão nativos e quais serão integração: folha, fiscal, contabilidade, vídeo, LIS e PACS/VNA?
3. Qual tier de disponibilidade será contratado por segmento e quais RPO/RTO serão garantidos?
4. O tenancy enterprise será pool, instância dedicada ou ambos sob control plane?
5. Quais certificações e homologações são requisito comercial, em qual ordem e com qual entidade responsável?

Sem essas decisões, o backlog tende a crescer horizontalmente sem fechar jornadas críticas.

## 14. Evidências principais no repositório

- `backend/apps/emr/models.py`
- `backend/apps/billing/models.py`
- `backend/apps/pharmacy/models.py`
- `backend/apps/hr/models.py`
- `backend/apps/patient_portal/`
- `backend/apps/imaging/`
- `backend/apps/fhir/`
- `backend/apps/core/models.py`
- `backend/vitali/settings/base.py`
- `frontend/app/(dashboard)/`
- `frontend/app/portal/`
- `docker-compose.prod.yml`
- `docker-compose.staging.yml`
- `docs/ARCH_TARGET_VISION.md`
- `docs/BACKUPS.md`
- `docs/IMAGING.md`
- `docs/LIS_INTEGRATION.md`
- `docs/SECURITY.md`

## 15. Próximo passo recomendado

Transformar as cinco decisões da seção 13 em um **charter de produto enterprise**, escolher a primeira vertical comercial e decompor somente a Onda 0 em RFCs e histórias estimáveis. O primeiro release não deve tentar entregar “tudo”: deve fechar, com qualidade enterprise, uma jornada clínica e uma jornada financeira completas.
