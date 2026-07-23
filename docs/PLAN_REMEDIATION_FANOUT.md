# Plano de ação — Remediação pós-auditoria fan-out

## Onda R0 — Bloqueadores de contrato (P0)

- Alinhar upload/listagem/aprovação NF-e aos endpoints e IDs reais.
- Alinhar estados da conciliação (`unmatched`, `review`, `matched`) e ações.
- Corrigir filtros de competência do cockpit DRE.
- Fazer devolução NF-e chamar o backend real.

**Gate:** upload NF-e, conferência, aprovação, importação bancária e DRE mensal
funcionam via browser contra staging; nenhum endpoint 404/405 no fluxo feliz.

## Onda R1 — Integridade transacional (P1)

- Locks e rechecagem sob `transaction.atomic()` em baixa, pagamento e aprovação.
- Impedir múltiplas transações para o mesmo recebível.
- Exigir mapeamento NF-e `confirmed` antes da aprovação.
- Validar CNPJ de destino contra o tenant.
- Idempotência forte para webhook/external ID e payload divergente.
- Auditoria para match, aprovação, estoque e devolução.

**Gate:** testes concorrentes/idempotência e auditoria verificável no PostgreSQL.

## Onda R2 — Qualidade enterprise (P2)

- DRE integrado a payables/cash-flow e realizado vs previsto.
- Valores monetários sem `float` no frontend.
- Restringir CRUD de fluxo de caixa e exigir segregação/aprovação.
- Validar coerência categoria receita/despesa.
- Justificativa obrigatória para aprovação de divergência 3-way.
- Remover credenciais fixas de CI/E2E.

**Gate:** CI completo, smoke, Playwright dos fluxos e revisão de segurança.

Cada onda deve ser mergeada e deployada separadamente; não avançar para a próxima
antes do gate da anterior.
