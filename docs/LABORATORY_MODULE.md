# Módulo de exames laboratoriais

## Escopo entregue

O primeiro corte operacional cobre o fluxo interno de exames laboratoriais:

1. catálogo de exames por tenant;
2. pedido vinculado a paciente e, opcionalmente, atendimento;
3. registro de coleta;
4. lançamento do resultado por item, com sinalizador de anormalidade;
5. validação nominal do resultado;
6. consulta do histórico de pedidos do paciente.

O corte concretiza a lacuna entre as primitivas já existentes de solicitação/laudo
FHIR (`ServiceRequest` e `DiagnosticReport`) e uma operação laboratorial utilizável.

## Fora deste corte

- integração bidirecional com LIS/equipamentos (HL7 v2/ASTM);
- assinatura ICP-Brasil e emissão de PDF do laudo laboratorial;
- portal do paciente e notificações de liberação;
- regras automáticas de referência por idade, sexo, gestação, método ou laboratório;
- microbiologia, antibiograma, anatomia patológica e cadeia de custódia;
- agendamento de exames e faturamento/TISS automático;
- imagem, DICOM, Orthanc e OHIF, que pertencem ao módulo PACS.

Esses itens continuam como evolução pós-MVP. O sinalizador de anormalidade deste
corte é informado pelo operador; o Vitali não deve inferir decisão clínica a partir
de uma faixa textual.

## Catálogo inicial

Execute no host Django:

```bash
python manage.py seed_lab_catalog --tenant demo --dry-run
python manage.py seed_lab_catalog --tenant demo
```

O comando é idempotente: cria códigos ausentes e atualiza nome, amostra e unidade
dos códigos conhecidos. Ele não desativa exames adicionais do tenant.

As faixas de referência ficam vazias de propósito. Antes do uso assistencial, um
responsável técnico deve cadastrar as faixas validadas pelo laboratório, levando em
conta método, população, idade e sexo. O catálogo inicial não é fonte de conduta.

## API

Base autenticada: `/api/v1/`.

| Operação | Endpoint |
|---|---|
| Listar/criar catálogo | `GET/POST lab-tests/` |
| Atualizar/inativar exame | `PATCH/DELETE lab-tests/{id}/` |
| Listar/criar pedidos | `GET/POST lab-orders/` |
| Filtrar pedidos | `GET lab-orders/?patient={id}&status={status}` |
| Registrar coleta | `POST lab-orders/{id}/collect/` |
| Lançar resultado | `POST lab-orders/{id}/items/{item_id}/result/` |
| Validar resultado | `POST lab-orders/{id}/items/{item_id}/validate/` |
| Cancelar pedido | `POST lab-orders/{id}/cancel/` |

Leitura exige `emr.read`; mutações exigem `emr.write`. Dados clínicos sensíveis
permanecem no schema do tenant e os campos narrativos/resultados são criptografados
em repouso. A API registra auditoria nas transições clínicas relevantes.

### Exemplo de pedido

```json
{
  "patient": "<uuid>",
  "encounter": "<uuid-opcional>",
  "clinical_indication": "Acompanhamento clínico",
  "test_ids": ["<uuid-do-exame>"]
}
```

### Exemplo de resultado

```json
{
  "result_value": "5.4",
  "abnormal_flag": "normal",
  "result_notes": ""
}
```

Valores aceitos em `abnormal_flag`: `normal`, `low`, `high`, `critical` e
`undetermined`.

## Operação segura

- Validar identidade do paciente e a amostra fora do sistema antes de registrar a coleta.
- Conferir unidade e faixa de referência capturadas no item do pedido.
- Validar resultados somente com profissional autorizado.
- Corrigir resultados por fluxo auditável; não sobrescrever histórico diretamente no admin.
- Tratar resultados críticos conforme o protocolo institucional — este MVP não notifica automaticamente.
