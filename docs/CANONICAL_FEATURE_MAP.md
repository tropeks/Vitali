# Vitali — Mapa de Funcionalidades Canônico (HIS/EMR)

> **Status:** documento CANÔNICO. Decisões de produto, arquitetura de informação (IA), RBAC e roadmap
> devem **seguir este documento**. Quando a realidade do código divergir daqui, ou este documento é
> atualizado (com justificativa), ou o código é ajustado — não se decide ownership/IA no achismo.
>
> **Origem:** pesquisa profunda (2026-07-26) em 7 domínios funcionais dos HIS líderes, feita por 7 agentes
> em paralelo com busca/leitura na web. **Referência primária: Philips Tasy** (HIS dominante no Brasil).
> **Comparação:** MV (Soul MV), TOTVS Saúde (RM/Protheus), Wareline, Pixeon; **contraste enterprise:**
> Epic e Oracle Health (Cerner). Inferências (onde a fonte pública é rasa) estão rotuladas `(inferido)`.
> Fontes por domínio no fim.

---

## 0. Como usar este documento

1. **O eixo é `Persona × Escopo`**, não "módulo". Toda funcionalidade tem um **dono** (o role que a
   opera) e um **escopo** (onde ela vive: corporativo/rede, unidade, setor, ou indivíduo/leito). É isso
   que resolve perguntas de IA como "escala é do RH ou do supervisor de setor?" (resposta na §3).
2. **Coluna Vitali** em cada tabela: `✅ tem` · `🟡 parcial` · `⬜ falta`. É o backlog canônico.
3. **Diferenciais**: a §9 lista onde o Vitali pode ganhar. O achado mais forte da pesquisa: o **módulo de
   Concessão/Comodato de equipamentos (TCX)** que já construímos é a **lacuna mais nítida do mercado** —
   nenhum HIS líder o trata como módulo de primeira classe. Já é vantagem; falta amadurecer.

### 0.1 Glossário de personas (roles)
| Sigla | Papel | Escopo natural |
|---|---|---|
| MED | Médico assistente / prescritor | leito/paciente |
| ENF | Enfermeiro assistencial | leito |
| **ENF-CHEFE** | Enfermeiro-chefe / coordenador de enfermagem da unidade | **setor** |
| TEC | Técnico/auxiliar de enfermagem | leito |
| FARM | Farmacêutico (clínico/hospitalar) | paciente/unidade |
| **COORD-MED** | Coordenador médico / chefe de plantão / diretor clínico | **setor/especialidade** |
| SUP-SETOR | Supervisor/coordenador de setor (hub operacional da unidade) | **setor** |
| RECEP | Recepcionista / registrador / agendador | ponto de atendimento |
| REGUL | Regulador (médico) de leitos/consultas | rede |
| FATUR | Faturista | unidade |
| AUDIT | Auditor de contas (prestador) / analista de glosa | unidade→corporativo |
| CONTROLLER | Controladoria / gestor de custos | corporativo |
| ALMOX | Almoxarife | central + setor |
| COMPRADOR | Comprador / gestor de suprimentos | corporativo |
| ENG-CLIN | Engenheiro clínico | corporativo (ativo institucional) |
| QUAL | Gestor de qualidade / NSP / NIR | setor→corporativo |
| CCIH | Comissão de controle de infecção | setor→corporativo |
| DPO | Encarregado de dados (LGPD) | corporativo |
| TI-INT | TI / integração / arquitetura | corporativo |
| RH-DP | RH/DP central | corporativo |
| GESTOR | Gestor executivo / diretoria / CIO | corporativo/rede |
| PACIENTE | Paciente (autoatendimento) | individual |

### 0.2 Níveis de escopo
- **Rede/Corporativo** — decisão/dado único para toda a instituição ou grupo (multiempresa). Ex.: tabela de convênio, MPI, custeio, políticas.
- **Unidade** — hospital/clínica específico dentro da rede. Ex.: censo, faturamento de unidade.
- **Setor** — posto/serviço dentro da unidade (UTI, PS, enfermaria X, imagem). Ex.: **escala**, requisição de insumo, pick de estoque.
- **Indivíduo/Leito** — paciente ou profissional específico. Ex.: prescrição, evolução, holerite.

---

## 1. Núcleo Assistencial / Clínico (PEP)

> Princípio enterprise confirmado: **o PEP é UM só, multiprofissional** (MED/ENF/FARM/fisio/nutri), com
> verticais especializados plugados por cima (CC, PS, UTI, Onco). NÃO construir "prontuário do médico" e
> "prontuário da enfermagem" separados. Três separadores enterprise: **CDS ativo governado**,
> **checagem beira-leito com código de barras (BCMA)**, **integração com dispositivos** (monitor/ventilador/bomba).

| Funcionalidade | Persona/Dono | Escopo | Ref. (Tasy/…) | Vitali |
|---|---|---|---|---|
| Evolução clínica multiprofissional (SOAP) | MED/ENF/multi | leito | Evolução; Epic NoteWriter | ✅ tem |
| Anamnese / história clínica | MED/ENF | indivíduo | Anamnese, História de Saúde | 🟡 parcial |
| Problemas/Diagnósticos (CID-10) | MED | indivíduo | Diagnósticos; Epic Problem List | ✅ tem |
| Alergias + alerta na prescrição | MED/ENF/FARM | indivíduo (transversal) | card SUEP | 🟡 parcial |
| Sumário 1-tela do paciente | todos | leito | **SUEP**; Epic Storyboard | 🟡 parcial |
| Prescrição eletrônica (CPOE) integrada (med+dieta+cuidado+exame) | MED | leito | CPOE; PIC | ✅ tem |
| Checagem de interações/dose/duplicidade (CDS) | MED+FARM | motor corporativo | **Micromedex**; Epic BPA | 🟡 parcial |
| Protocolos / order sets gerenciados | MED usa / comissão cura | corporativo→leito | **Mentor**; Epic SmartSets | 🟡 parcial |
| Antimicrobianos / stewardship | MED+CCIH+FARM | corporativo→leito | (via CCIH) | ⬜ falta |
| Prescrição/sumário de alta | MED | indivíduo | Alta Médica, Planejamento de Alta | 🟡 parcial |
| SAE (NANDA/NIC/NOC) — histórico→diag→prescrição→evolução enferm. | ENF (privativo) / TEC executa | leito | SAE; MV NANDA-I | ⬜ falta |
| Aprazamento | ENF | leito→setor | Aprazamento | 🟡 parcial |
| Checagem de medicação beira-leito (BCMA) | TEC/ENF | leito | **ADEP™**; Epic eMAR+BCMA | ⬜ falta |
| Sinais vitais e monitorização + device integration | TEC/ENF | leito | Sinais Vitais; Epic Flowsheets | ✅ tem (device ⬜) |
| Balanço hídrico (ganhos e perdas) | TEC/ENF | leito | Ganhos e Perdas | ⬜ falta |
| Escalas/índices (Braden/Morse/Glasgow/dor) → ação automática | ENF | leito | Escalas e Índices | 🟡 parcial |
| Escores de deterioração (NEWS/MEWS), sepse, código azul | ENF aciona / MED responde | corporativo→leito→setor | Escalas+Mentor; Epic Deterioration Index | ✅ tem ("Deterioração") |
| UTI (APACHE/SOFA, ventilação, drogas vasoativas) | intensivista/ENF | setor+leito | Epic iView | ⬜ falta |
| Centro Cirúrgico (mapa, checklist OMS, contagem cavidade, OPME, descrição) | cirurgião/ANEST/ENF-CC | corporativo→sala | **PEPO/CLEPA/APAE**; Epic OpTime | ⬜ falta |
| Pronto-Socorro (classificação de risco Manchester + track board) | ENF classificador/MED | setor | Manchester; Epic ASAP | 🟡 parcial (fila R1) |
| Obstetrícia (partograma, CTG) | obstetra/ENF-obst | setor | Epic Stork | ⬜ falta |
| Oncologia/Quimio (protocolos, ciclos, dose cumulativa) | oncologista/FARM-onco/ENF | corporativo→ciclo | Epic Beacon | ⬜ falta |
| CDS / linhas de cuidado governadas | consome MED/ENF / cura comissão | corporativo | **Mentor**; Epic BPA+preditivos | ⬜ falta |

---

## 2. Fluxo do Paciente / Acesso

| Funcionalidade | Persona/Dono | Escopo | Ref. | Vitali |
|---|---|---|---|---|
| Agenda médica / consultas | RECEP/setor | setor OU central | Agendas; Epic Cadence | ✅ tem |
| Agenda de salas/recursos/equipamentos (anti-double-booking) | RECEP/coord. diagnóstico | setor→central | Agenda Cirúrgica | ✅ tem (AppointmentResource) |
| Central de agendamento (multi-tipo/multi-unidade) | RECEP-central | corporativo | Central de Agendamento | 🟡 parcial |
| Overbooking / encaixe auditado | RECEP (permissão elevada) | individual→central | Encaixe | ✅ tem (`emr.appointment_encaixe`) |
| Lista de espera + preenchimento de vaga | RECEP/REGUL | setor/rede | Lista de Espera; Epic Fast Pass | 🟡 parcial |
| Confirmação SMS/WhatsApp | (terceirizado nos concorrentes) | individual | integradores externos | ✅ tem (WhatsApp nativo) — **diferencial** |
| Cadastro de paciente | RECEP | individual | Epic Prelude | ✅ tem |
| **MPI / dedupe probabilístico** | RECEP / data steward | **corporativo** | Epic Prelude MPI | 🟡 parcial (MPI app) |
| CNS / identificação SUS | RECEP | nacional | — | 🟡 parcial |
| Validação de elegibilidade de convênio | RECEP→FATUR | individual, regra corporativa | Autorização TISS; Epic X12 270/271 | 🟡 parcial |
| Internação / Admissão (ADT) | RECEP-internação/REGUL | unidade | Internação; Epic Prelude | ⬜ falta |
| Gestão de leitos / mapa de ocupação (+ housekeeping/transporte) | bed manager / ENF de fluxo | unidade→corporativo | Gestão de Leitos; Epic Grand Central | ⬜ falta |
| Censo hospitalar / gestão à vista | GESTOR | corporativo | painel; Wareline Gestão à Vista | 🟡 parcial |
| Alta administrativa × clínica × hospitalar (3 eventos) | MED/RECEP/ENF+bed mgr | individual→corporativo | Tasy (3 altas) | ⬜ falta |
| Regulação de leitos / central de regulação (+SISREG) | **REGUL** (médico) | rede/regional | MV Central de Regulação; SISREG | ⬜ falta |
| Fila cirúrgica | coord. CC/REGUL | setor→corporativo | Agenda Cirúrgica | ⬜ falta |
| Autorização de procedimentos (TISS) | FATUR | individual, regra corporativa | Gerenciamento de Autorizações | 🟡 parcial |
| Senhas / totem / painel de chamada | PACIENTE→ENF/RECEP | setor | TOTVS Toten | ✅ tem (R1) |
| Classificação de risco (Manchester) formal | **ENF classificador** | setor | RM SAU Classificação de Risco | 🟡 parcial |
| Portal do paciente / agendamento online | PACIENTE | individual sobre base corporativa | Epic MyChart | ✅ tem (+ PIX — **diferencial**) |
| Telemedicina | MED+PACIENTE | individual | MV Teleconsulta | ✅ tem |

---

## 3. Gestão de Pessoas & Operações — **DECISÃO CANÔNICA DE OWNERSHIP**

> **A escala de plantão é DESCENTRALIZADA — pertence ao SUPERVISOR/COORDENADOR DE SETOR, não ao RH central.**
> Evidência: literatura de enfermagem (SciELO/Acta Paul Enferm: a escala mensal é responsabilidade do
> enfermeiro-gestor da unidade), POPs hospitalares, e a arquitetura dos líderes — no **Tasy** a escala está
> no módulo assistencial de Enfermagem; no **TOTVS** fica em *Gestão Hospitalar → Postos de Enfermagem* (seleção
> de **Setor**), separada do *RM RH* (ponto/folha). O RH/DP central **consome** a escala (ponto, banco de horas,
> adicional noturno, repasse), não a origina.
> **Correção regulatória:** COFEN **543/2017 foi revogada pela 743/2024** — dimensionamento deve seguir a 743.

### Matriz de propriedade (a IA correta)
| Função | Cria | Aprova | Vê | Escopo |
|---|---|---|---|---|
| Escala de enfermagem | **ENF-CHEFE** | Gerente de enfermagem | equipe (TEC) | **SETOR** |
| Escala médica de plantão | **COORD-MED** | diretor clínico | plantonistas | **SETOR/especialidade** |
| Dimensionamento (COFEN 743/2024) | ENF/RT | gerência enferm. | coordenação | **SETOR** (alimenta a escala) |
| Troca/folga/cobertura | funcionário (self) | **SUP-SETOR** | equipe | individual→setor |
| Ponto/banco de horas | sistema (contra a escala) | SUP-SETOR abona → RH-DP fecha | funcionário | **CENTRAL** (abono no setor) |
| Folha/férias/benefícios/admissão/ASO/dependentes/cargos | **RH-DP** | RH | funcionário (self) | **CENTRAL** |

**Recomendação canônica:** criar um **"Painel de Setor"** (superfície do coordenador) que reúne escala +
dimensionamento + aprovação de trocas/folgas + indicadores do setor, com o **funcionário em autoatendimento**
e o **RH central como consumidor downstream**. Manter o **RH administrativo** (admissão, cargos, folha, férias,
benefícios, ASO, dependentes) como domínio **central** separado.

| Funcionalidade | Persona/Dono | Escopo | Vitali (hoje) | Ação canônica |
|---|---|---|---|---|
| Escala/plantões (DutyRoster/RosterSlot) | **ENF-CHEFE/COORD-MED** | **setor** | 🟡 existe em `/rh/escalas` **mas gated `adminOnly`+`HRAccessPermission`** | **MOVER para Painel de Setor**; nova permissão `roster.manage` p/ coordenador; escopo por unidade |
| Troca/folga/cobertura self-service | funcionário → SUP-SETOR | individual→setor | ⬜ falta | construir |
| Dimensionamento (743/2024) | ENF/RT | setor | ⬜ falta | construir (alimenta escala) |
| Lotação (EmployeeAssignment) | RH-DP / SUP-SETOR | central/setor | ✅ `/rh/lotacoes` | manter; revisar quem gerencia |
| Afastamentos/férias (maker-checker) | funcionário → RH/gestor | central | ✅ `/rh/afastamentos` | manter no RH central ✓ |
| Cargos / Dependentes | RH-DP | central | ✅ `/rh/cargos`,`/dependentes` | manter no RH central ✓ |
| Ponto/banco de horas | sistema/RH-DP (abono setor) | central | ⬜ falta | construir |
| Folha / benefícios / ASO / admissão | RH-DP | central | ⬜ falta | construir |

---

## 4. Apoio Diagnóstico (SADT)

> Princípio de arquitetura confirmado: **bidirecionalidade é o critério de maturidade** em toda integração
> (LIS↔analisador, RIS↔PACS, RIS↔telerradiologia) — nunca só "enviar", sempre fechar o ciclo de retorno.
> **Microbiologia e Anatomia Patológica são módulos de 1ª classe** (fluxo de dias/macroscopia quebra o modelo
> "pedido→resultado em minutos"). **Delta check + CQ (Westgard/Levey-Jennings) são feature nativa do motor de
> resultado**, não relatório pós-fato.

| Funcionalidade | Persona/Dono | Escopo | Ref. | Vitali |
|---|---|---|---|---|
| Pedido de exame (SADT) + etiqueta/barcode | MED solicita / RECEP | ponto→corporativo | Tasy Solicitação | ✅ tem |
| Coleta + identificação de amostra (barcode beira-leito) | TEC-coleta/ENF | setor | Epic Rover | 🟡 parcial |
| Mapa de trabalho / filas priorizadas | biomédico/técnico | setor | Produção e Análise | 🟡 parcial |
| Interfaceamento de analisadores (ASTM/HL7, bi-direcional) | biomédico + TI-INT | corporativo (middleware) | ATRIA; Pixeon | ⬜ falta |
| Resultado + valores de referência + assinatura | biomédico/FARM-bioq | corporativo | — | ✅ tem |
| **Delta check** (variação vs prévio, bloqueia liberação) | biomédico | motor de resultado | literatura QC | ✅ tem (A3/A4) |
| Controle de qualidade (CIQ/CEQ, Westgard, Levey-Jennings) | RT laboratório | corporativo | RDC 302/2005 | ⬜ falta |
| Microbiologia (cultura/antibiograma/multirresistência→CCIH) | microbiologista | setor→corporativo | Cerner PathNet Micro | ⬜ falta |
| Anatomia Patológica (macroscopia→laudo, citopatologia) | patologista/histotec. | setor especializado | Epic Beaker AP | ⬜ falta |
| Imagem: pedido + agenda por modalidade | RECEP/PACIENTE | unidade→central | Pixeon RIS | ✅ tem |
| DICOM Modality Worklist (MWL) + MPPS | técnico radiologia + TI-INT | corporativo | Epic Radiant | 🟡 parcial |
| Visualizador (PACS/viewer) + prior fetch | radiologista/especialistas | corporativo | OHIF; Pixeon Arya; MV VIDA | ✅ tem (viewer/OHIF) |
| Laudo estruturado + Central de Laudos (voz, worklist) | radiologista | corporativo | Pixeon Central de Laudos | 🟡 parcial |
| VNA / distribuição de imagens multi-PACS | TI-INT | corporativo | (enterprise-only) | ⬜ falta |
| Telerradiologia (retorno automático bidirecional) | radiologista remoto + TI-INT | rede | ConnectHL7 | ⬜ falta |
| Apoio externo / lab de apoio + portal de resultados | gestor rede apoio / PACIENTE | corporativo | Wareline SADT | 🟡 parcial |

---

## 5. Faturamento & Financeiro

> 6 blocos que devem virar epics: (1) Cadastros/Regras; (2) Autorização+Conta; (3) TISS; (4) SUS; (5)
> Auditoria+Glosas; (6) Financeiro/Controladoria. **3 personas distintas** com telas/permissões próprias:
> **FATUR** (lança), **AUDIT** (audita antes do envio), **analista de glosa** (trata retorno). Maior gap
> competitivo do setor: **prevenção proativa de glosa + contract modeling** (Epic Resolute) — os BR são reativos.

| Funcionalidade | Persona/Dono | Escopo | Ref. | Vitali |
|---|---|---|---|---|
| Cadastro de convênios + regras + vigência | FATUR/analista | corporativo | Cadastrando Convênios | 🟡 parcial |
| Tabelas TUSS/CBHPM/Brasíndice/Simpro (atualização) | analista precificação | corporativo | Preços de Materiais | 🟡 parcial (TUSS ✅) |
| Autorização TISS | FATUR | individual, regra corp. | Gerenciamento de Autorizações | 🟡 parcial |
| Guias TISS (SP/SADT, internação, consulta, honorários) + lotes XML | FATUR | unidade | — | ✅ tem (guides, SP/SADT) |
| Conta do paciente (consumo→fechamento) | FATUR + ENF/FARM (consumo) | unidade | Conta Paciente | 🟡 parcial |
| Gestão de pacotes | analista | corporativo | Gestão de Pacotes | ⬜ falta |
| Faturamento SUS (BPA/APAC/AIH/SIGTAP/CIHA) | FATUR-SUS | unidade→gestor público | FFIS | ⬜ falta |
| Auditoria de conta pré-envio | **AUDIT** (prestador) | unidade | Auditoria Conta Paciente | ⬜ falta |
| Glosas: análise + recurso + conciliação | **analista de glosa** | corporativo | Recurso de Glosas | ✅ tem (glosas) |
| Repasse a terceiros (médicos/coop.) | CONTROLLER | corporativo | Repasse para Terceiros | ⬜ falta |
| Contratos/negociação de preço por plano | gerência comercial | corporativo | Condições Contratuais | 🟡 parcial (price tables) |
| Lab → guia SP/SADT (bridge) | FATUR | unidade | — | ✅ tem (A5/A6) |
| Contas a pagar/receber, tesouraria, contabilidade | CONTROLLER | corporativo | Controladoria | ⬜ falta |
| Custeio hospitalar (ABC/absorção, centro de custo, rateio) | CONTROLLER | corporativo | Custos | 🟡 parcial (P&L concessão) |
| Dashboards financeiros (glosa/margem/inadimplência) | GESTOR | corporativo | EIS | 🟡 parcial |

---

## 6. Suprimentos & Farmácia

> Achado forte: **Comodato de equipamentos** e **requisição/kanban por setor** são as lacunas mais nítidas —
> nenhum HIS líder os trata como módulo nomeado de 1ª classe (ver §9). Vitali já tem o comodato (TCX).

| Funcionalidade | Persona/Dono | Escopo | Ref. | Vitali |
|---|---|---|---|---|
| Dose unitária / dispensação | TEC-farm/FARM | setor (param. central) | Tasy Dose Unitária | 🟡 parcial |
| Farmácia satélite / dispensário eletrônico | FARM/TEC-setor | setor, gov. central | (Pyxis integ.) | ⬜ falta |
| Farmácia clínica | FARM clínico | paciente/unidade | TOTVS Farmácia Clínica Digital | 🟡 parcial |
| Validação farmacêutica da prescrição | FARM | paciente, regra corp. | Cerner PharmNet | 🟡 parcial |
| Conciliação medicamentosa | FARM clínico | paciente (transições) | (sem módulo nomeado) | ⬜ falta |
| Antimicrobianos / stewardship | FARM+CCIH | corporativo→paciente | Cerner Clinical Surveillance | ⬜ falta |
| Quimioterapia / manipulação | FARM-onco | setor | Tasy Quimio | ⬜ falta |
| Farmacovigilância | FARM/CCIH | corporativo | (processo, sem módulo) | ⬜ falta |
| Estoque multi-almoxarifado + curva ABC + ressuprimento | ALMOX/FARM | corporativo+setor | Tasy Estoque | ✅ tem (pharmacy stock) |
| Inventário físico/cíclico | ALMOX/AUDIT | unidade+corp. | Tasy Inventário | 🟡 parcial |
| Rastreabilidade lote/validade (FEFO) | ALMOX/FARM | corporativo | — | ✅ tem |
| **Kanban / reposição por setor** | **SUP-SETOR** ↔ ALMOX | setor→central | (gap de mercado) | 🟡 parcial (req. concessão) |
| **Requisição de insumos por setor** | **SUP-SETOR** | setor→central | Tasy Requisição | ✅ tem (concessão logística) |
| Cotação / ordem de compra / alçada | COMPRADOR/GESTOR | corporativo | Bionexo | ⬜ falta |
| Recebimento / inspeção / avaliação fornecedor | ALMOX | unidade/central | Tasy Recebimento | ⬜ falta |
| Contratos de fornecimento | COMPRADOR | corporativo | Tasy Contratos | 🟡 parcial (contratos concessão) |
| OPME (autorização + consignação/rastreio série) | FARM/ALMOX-OPME + COMPRADOR | setor+corporativo | Odin (nicho) | ⬜ falta |
| Gases medicinais | ENG-CLIN+FARM | corporativo | (item de estoque especial) | ⬜ falta |
| Rouparia / CME (rastreio instrumental por kit+barcode) | TEC-CME | setor, compliance corp. | Tasy kit+barcode | ⬜ falta |
| **Comodato de equipamentos** (ativo, contrato, manutenção, consumo vinculado) | **ENG-CLIN** + COMPRADOR | corporativo | **lacuna de mercado** | ✅ tem (Concessão B1-B6) — **diferencial** |

---

## 7. Governança, Qualidade, Regulatório & Interoperabilidade

| Funcionalidade | Persona/Dono | Escopo | Ref. | Vitali |
|---|---|---|---|---|
| Gestão de protocolos clínicos (aderência/alerta) | QUAL/comissão | setor→corporativo | Tasy protocolos | ⬜ falta |
| Indicadores de qualidade (core measures) | QUAL/NIR | unidade+corporativo | MV Go Quality; Epic Healthy Planet | 🟡 parcial |
| Não conformidade / CAPA | QUAL/AUDIT/SUP-SETOR | setor→corporativo | MV Go Quality | ⬜ falta |
| Gestão de risco / eventos adversos (NSP) → NOTIVISA | NSP/CCIH/QUAL | setor→corporativo | (notificação manual hoje) | ⬜ falta |
| Comissões (CCIH, F&T, prontuário) | CCIH/FARM/NIR | setor→corporativo | Tasy CCIH | ⬜ falta |
| Certificação PEP SBIS/CFM (NGS2) | TI-INT/compliance | corporativo (do produto) | Tasy NGS2 | 🟡 parcial (signatures) |
| Assinatura digital ICP-Brasil | MED/todos | individual | — | ✅ tem (signatures) |
| CNES / e-SUS sync | TI-INT | corporativo | DATASUS | 🟡 parcial (CNES catálogo) |
| LGPD: consentimento, trilha, anonimização, direitos do titular | DPO | corporativo | MV módulo LGPD | 🟡 parcial (privacidade + audit) |
| RNDS (FHIR R4 + ICP-Brasil) | TI-INT | corporativo | DATASUS RNDS | 🟡 parcial (fhir app) |
| FHIR R4 / HL7 v2 | TI-INT | corporativo | Epic Care Everywhere | 🟡 parcial |
| Terminologias (CID/CIAP/LOINC/SNOMED/TUSS/CBO/CNES) | TI-INT/analista | corporativo | Portaria 2073/2011 | ✅ tem (CID/TUSS/CBO/CNES/LOINC/UCUM — A1) |
| Multiunidade / multiempresa | GESTOR/CIO | rede | Tasy (caso Unimed 10-em-1) | ✅ tem (django-tenants) |
| BI / analytics / dashboards | GESTOR/BI | corporativo | MV linha "Go" | 🟡 parcial |
| RBAC / perfis / trilha de auditoria / break-glass | TI-INT/DPO | corporativo | Epic (audit granular) | ✅ tem (RBAC+AuditLog) |
| SSO / MFA | TI-INT | corporativo | — | 🟡 parcial |
| Portais segmentados (paciente/médico/prestador) | gestor relacionamento | setor→corporativo | MV Medic/Personal Health; Epic MyChart | 🟡 parcial |
| Gestão de contratos / CRM / ouvidoria | gestor relacionamento | corporativo | Tasy Operadoras | ⬜ falta |

---

## 8. Contraste enterprise (Brasil × Epic/Cerner) — o que "enterprise" significa

- **Identidade:** BR tem CNS nacional (público); EUA tem MPI proprietário. Vitali deve tratar MPI + CNS como camada única.
- **CDS ativo governado** (base clínica curada + protocolos versionados) é o maior separador clínico. Vitali: parcial.
- **BCMA beira-leito** e **integração com dispositivos** (monitor/ventilador/bomba): separadores de segurança. Vitali: falta.
- **Prevenção proativa de glosa + contract modeling** (Epic Resolute): BR é reativo. Espaço de diferenciação.
- **Interoperabilidade peer-to-peer** (Care Everywhere) vs. no Brasil majoritariamente regulatória (enviar à RNDS).
- **Auditoria/segurança documentada** (break-glass, log de API/exportação) é mais madura no Epic — Vitali já tem base RBAC+AuditLog forte.

---

## 9. Onde o Vitali ganha (diferenciais reais mapeados na pesquisa)

1. **Comodato/Concessão de equipamentos (TCX) — já construído (B1-B6).** Lacuna mais nítida do mercado:
   nenhum HIS líder tem módulo de 1ª classe nomeado (aparece difuso em "engenharia clínica/ativos"). **Manter e aprofundar.**
2. **Requisição/kanban por setor com persona "supervisor de setor" de 1ª classe** — pouco explorado pelos concorrentes. Vitali já tem o fluxo logístico da concessão; generalizar para farmácia/almoxarifado.
3. **WhatsApp nativo** (confirmação, fila, portal) — nos concorrentes é terceirizado. Já é diferencial.
4. **PIX nativo no portal do paciente** — nem Tasy nem MyChart documentam. Já é diferencial.
5. **RNDS Conformance Statement público** (recursos FHIR suportados) — nenhum concorrente publica. Barato e diferenciador.
6. **LGPD-native** (ROPA/RIPD, direitos do titular, trilha granular) — nenhum BR tem módulo robusto documentado.
7. **NOTIVISA/farmacovigilância com integração automática** — hoje manual em todos. Diferencial técnico.

---

## 10. Implicações de roadmap (backlog canônico)

**Refatorar já (dívida de IA, barato):**
- Mover **Escala** do RH central para um **Painel de Setor** (dono = coordenador/enfermeiro-chefe), com permissão `roster.manage` e escopo por unidade. Manter cargos/lotação/afastamentos/dependentes no RH central. (§3)

**Aprofundar o diferencial (curto prazo):**
- Concessão/Comodato: fechar `freight_cost` no serializer, toggle de tier por tenant (`platform/tenants/[id]`), generalizar requisição-por-setor para o almoxarifado geral.

**Grandes lacunas por valor (médio prazo, candidatas a ondas):**
- ADT + Gestão de leitos + censo (§2) · SAE de enfermagem + BCMA (§1) · Faturamento SUS (§5) · Auditoria de conta + prevenção proativa de glosa (§5) · Centro Cirúrgico/PEPO (§1) · Interfaceamento de analisadores + CQ Westgard (§4) · RNDS/FHIR conformance (§7).

**Regras transversais a seguir sempre:**
- PEP único multiprofissional (não separar por profissão). · Bidirecionalidade em toda integração. · Toda feature nova declara `persona × escopo` + RBAC. · Delta check/CQ nativos no motor de resultado.

---

## Apêndice — Fontes por domínio
Pesquisa completa (URLs, inferências rotuladas) preservada nos relatórios dos 7 agentes desta rodada
(2026-07-26). Referências primárias por domínio: Philips Tasy (trilhas Veduca, philips.com.br, bionexo),
MV (mv.com.br), TOTVS (centraldeatendimento/produtos.totvs.com), Wareline, Pixeon, Epic (epic.com/open.epic),
Oracle Health/Cerner; normas: COFEN 743/2024, RDC ANVISA 302/2005, SBIS-CFM (NGS1/2/3), Portaria MS 2073/2011,
padrão TISS/ANS, RNDS FHIR (rnds-fhir.saude.gov.br), ONA/JCI/Qmentum, SISREG/DATASUS.

> **Manutenção deste documento:** ao decidir algo que contrarie este mapa, atualizar a seção correspondente
> com a justificativa e a data. Este é o contrato de produto/IA do Vitali.
