# Backbone de integrações

Fundação tenant-scoped e independente de protocolo para tráfego assíncrono.

## Entrada

Adaptadores normalizam mensagens e chamam InboxService.receive. A chave de
idempotência é obrigatória; colisões com conteúdo diferente são rejeitadas.
Payload e headers são criptografados em repouso. O worker
governance.process_inbox faz claim com SKIP LOCKED, recupera locks abandonados,
aplica retry exponencial e move mensagens esgotadas para dead.

Handlers são registrados com register_inbox_handler. Nenhum protocolo (HL7,
ASTM, FHIR ou DICOM) pertence a esta camada.

## Saída

Produtores gravam DomainEventOutbox na mesma transação da alteração de domínio.
Publishers são registrados com register_outbox_handler. O worker
governance.dispatch_outbox oferece locks concorrentes, retry exponencial,
recuperação de locks abandonados e estado terminal dead.

## Operação e segurança

- GET /api/v1/governance/integration-inbox/
- POST /api/v1/governance/integration-inbox/{id}/replay/
- GET /api/v1/governance/integration-outbox/
- POST /api/v1/governance/integration-outbox/{id}/replay/

Leitura exige integrations.operations.read; replay exige integrations.replay e
gera AuditLog. Payloads não são expostos pela API. Filtros por
estado/tipo/origem e busca por chaves operacionais estão disponíveis. Os
workers retornam contadores de lote e emitem logs estruturados por schema, tipo
e tentativa.

O chamador sempre informa schema_name ao enfileirar o worker. Isso torna o
contexto tenant explícito e evita processamento acidental no schema público.
