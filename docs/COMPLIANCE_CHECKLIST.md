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
- [ ] **Retenção de 20 anos**: Validado que exclusões de prontuário solicitadas via portal geram apenas tarefas operacionais e **nunca** apagam os registros do banco (cumprindo a retenção exigida pelo CFM).

## 3. Assinatura Digital (ICP-Brasil)
- [ ] **Certificados A1 Instalados**: Os certificados A1 dos médicos estão associados corretamente aos seus perfis no sistema.
- [ ] **Verificação de Revogação (CRL/OCSP)**: Se desejado, a checagem de revogação está ligada via variável `ICP_BRASIL_CHECK_REVOCATION=True` e a comunicação com os endpoints do ITI não está bloqueada pelo firewall.
- [ ] **Truststore da AC Raiz**: A âncora de confiança do ITI foi importada/atualizada rodando `python manage.py refresh_icp_truststore` na infraestrutura de produção.
- [ ] **Integração no Fluxo**: Assinaturas de Encounters e Prescriptions geram adequadamente as chaves de assinatura e verificações com o ICP. Fail-open documentado: a falta temporária do certificado permite conclusão do atendimento com aviso `is_icp_brasil=False`.

---
*Assinatura do Responsável de Implantação:* _________________________
*Data:* ___/___/20__
