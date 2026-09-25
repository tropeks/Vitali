# Vitali - GA Compliance Checklist (LGPD, CFM & ICP-Brasil)

Antes de promover um tenant de clínica para produção, o operador deve percorrer este checklist de prontidão legal e técnica.

## 1. Privacidade e Proteção de Dados (LGPD)
- [ ] **Política de Privacidade**: A clínica aprovou e publicou o texto final da política de privacidade? (Base: `frontend/app/(public)/privacidade`).
- [ ] **Cookie Consent**: O banner de cookies e registro de consentimento está rodando? (Base: `CookieBanner.tsx`).
- [ ] **Direitos do Titular (Patient Portal)**: A funcionalidade de exportação de dados (JSON/PDF) e solicitação de retificação/eliminação no portal do paciente foi testada?
- [ ] **DPA (Data Processing Agreement)**: O contrato de processamento de dados entre a Vitali (Operadora) e a Clínica (Controladora) foi assinado? (Template base: `docs/DPA_TEMPLATE.md`).
- [ ] **RIPD (Relatório de Impacto)**: A clínica elaborou seu RIPD? (Template base: `docs/RIPD_TEMPLATE.md`).
- [ ] **DPO (Data Protection Officer)**: O Encarregado de Dados da clínica foi devidamente cadastrado no painel `/configuracoes/privacidade`?
- [ ] **Criptografia em Repouso**: A encriptação de PII no banco de dados está ativa e validada.

## 2. Padrões Clínicos e Retenção (CFM)
- [ ] **Trilha de Auditoria (Audit Log)**: Todas as ações clínicas (criação de registros, alterações, assinaturas) estão gerando as trilhas de auditoria imutáveis.
- [x] **Trilha imutável no banco**: `core_auditlog` recusa `UPDATE`/`DELETE`/`TRUNCATE` por trigger e `REVOKE` (migration `0019`, reaplicada na tabela particionada pela `0043`).
- [x] **Trilha de leitura de prontuário** — ordens 016 a 019. O roteador do Django enumera as views, nunca `grep`; `apps/core/audit_coverage.py` classifica (caminho até `emr.Patient` por FK/OneToOne/M2M, sem atravessar `core.User`/`Tenant`/`Role`; ou model em `MODELS_SENSIVEIS`); o teste reprova view ou rota `GET` sem trilha. Fechamento da 019: 154 views · 74 exigem trilha · 321 rotas `GET` · 0 sem cobertura. Detalhe em `docs/SECURITY.md` §3.6.1.
- [x] **Faixa 2 — RH com dado pessoal sensível** (LGPD art. 5º II e art. 37) — ordens 017 e 018: afastamento, exame ocupacional, dependente e ponto deixam trilha; `?employee=` filtra de verdade.
- [x] **Retenção de 20 anos da trilha** — ordem 021 e `docs/adr/ADR-0001-retencao-auditoria-20-anos.md`: 240 meses por tenant (`TenantAuditRetention.retention_months=240`), expurgo desligado de fábrica (`purge_enabled=False`). Base: Res. CFM 1.821/2007 art. 8; Lei 13.787/2018 art. 6.
- [x] **Partição e isolamento por tenant da trilha** — ordem 020: `core_auditlog` particionada por mês (`created_at`) e por tenant (`schema_name`), DEFAULT nos dois níveis; `DROP` de partição exige recibo de exportação fria verificado.
- [x] **Partições criadas no caminho real** — ordem 021: `ensure_audit_partitions` depois do `migrate_schemas` e diário no Celery Beat.
- [ ] **Sem linha em folha DEFAULT**: a última execução de `ensure_audit_partitions` imprimiu `nenhuma linha em folha DEFAULT`. Se imprimiu `ALERTA`, rode `backfill_audit_partitions` antes do go-live (ver `docs/RUNBOOK.md` §8).
- [ ] **Expurgo continua desligado para o tenant**: nenhuma linha de `TenantAuditRetention` com `purge_enabled=True` sem ordem do Imediato.
- [ ] **Retenção de 20 anos do prontuário**: Validado que exclusões de prontuário solicitadas via portal geram apenas tarefas operacionais e **nunca** apagam os registros do banco (cumprindo a retenção exigida pelo CFM).

## 3. Assinatura Digital (ICP-Brasil)
- [x] **Truststore sobrevive ao deploy** — ordem 014: volume `icp_truststore` montado em `/app/apps/signatures/truststore` no `django` de staging e produção.
- [x] **Truststore vazio recusa a assinatura** — ordem 015: com `ICP_BRASIL_ENFORCE_CHAIN=True` (padrão; staging e produção) o endpoint responde `400` com `trust store not populated` e não grava nada. Só `development.py` (dev/CI) fixa `False`.
- [x] **Chave do médico não fica no servidor**: `pkcs12_b64` e `pkcs12_password` são campos `write_only` do corpo da requisição; `DigitalSignature` não guarda chave nem senha.
- [ ] **Truststore da AC Raiz populado**: rode `python manage.py refresh_icp_truststore --file <ACcompactado.p7b>` **dentro do contêiner** de produção, com o bundle baixado pelo navegador (o download direto falha por TLS do `acraiz.icpbrasil.gov.br`, ordem 014). Confira que o diretório tem as âncoras, não só `README.md`. Sem isso, **ninguém assina** (ordem 015).
- [ ] **Certificados A1 dos médicos**: cada médico assina com seu `.pfx` em staging antes do go-live.
- [ ] **Verificação de Revogação (CRL/OCSP) — pré-requisito de produção, ainda desligada**: hoje nenhum ambiente define `ICP_BRASIL_CHECK_REVOCATION`, então vale o padrão `False` e certificado revogado ainda assina. Ligar exige: endpoints do ITI alcançáveis pelo firewall, teste com os `.pfx` reais em staging (o modo `require` é fail-closed e pode recusar bundle que hoje passa), e só então `ICP_BRASIL_CHECK_REVOCATION=True`. Ver `docs/ICP_BRASIL.md`.
- [ ] **Integração no Fluxo**: Assinaturas de Encounters e Prescriptions geram adequadamente as chaves de assinatura e verificações com o ICP. Atenção: não existe mais fail-open com store vazio — sem âncoras a assinatura é recusada (ordem 015).

## 4. Pendências conhecidas (não bloqueiam este checklist, mas precisam de ordem própria)
- [ ] **Revogação ICP-Brasil ligada em produção** — ver seção 3.
- [ ] **Destino frio S3 Glacier da trilha** — decidido pelo Capitão na ordem 020 (Glacier Flexible, São Paulo, Object Lock em modo compliance, credencial só-grava), **não implementado**: só existe `LocalDiskColdStorageBackend`. Fora da ordem 021; precisa de `boto3` e prova em MinIO.
- [ ] **Sorologia de doador de sangue fora do crivo** — `emr.BloodDonor` e `emr.BloodBagSerology` não alcançam `emr.Patient` e não estão em `MODELS_SENSIVEIS`; o guarda de cobertura não exige trilha ali. As duas views herdam `AuditReadMixin` hoje, mas nada reprova se ele sair.
- [ ] **`core_auditlog_pre020`** — tabela antiga de auditoria, preservada pela ordem 020. Nenhum `DROP` sem aceite explícito do Imediato.

---
*Assinatura do Responsável de Implantação:* _________________________
*Data:* ___/___/20__
