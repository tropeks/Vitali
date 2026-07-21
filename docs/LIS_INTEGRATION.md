# Integração LIS e equipamentos

O Vitali expõe uma fronteira de integração, não um driver físico de analisador. Gateways que
falam ASTM, serial, TCP/MLLP ou protocolos proprietários devem normalizar a mensagem e entregá-la
por HTTPS. Marcar o formato como `astm` significa “ASTM já normalizado”; não significa que o
Vitali abriu uma conexão ASTM com o equipamento.

## Entrada segura

Configure `LIS_INBOUND_SECRET` com um segredo longo e exclusivo por stack. Envie:

- `POST /api/v1/lab-integrations/inbound/`
- `X-Vitali-LIS-Secret: <segredo>`
- `X-Vitali-LIS-Source: <gateway-estável>`
- corpo `{"format":"canonical","payload":{...}}` ou `format: "hl7_v2"`

O formato canônico exige `message_id`, `accession_number` e `results` com `code` e `value`.
HL7 aceita somente ORU, com MSH-10, OBR-3 e ao menos um OBX válido. O parser é deliberadamente
restrito; não é uma implementação geral de HL7. O trio origem, message id e direção garante
idempotência. Reutilizar um message id com conteúdo diferente retorna conflito.

Mensagens válidas ficam pendentes. Um operador com `emr.write` revisa e aplica em
`POST /api/v1/lab-integrations/{id}/apply/`. A aplicação é atômica, exige accession único,
pedido coletado e códigos locais ou LOINC correspondentes a itens ainda não validados. O sistema
não calcula flag clínica nem escolhe faixa de referência automaticamente.

## Saída

Usuários com `emr.read` podem gerar uma representação ORM em
`GET /api/v1/lab-orders/{id}/orm/`. A mensagem usa MRN, accession e códigos de exame; não inclui
o nome do paciente. O envio pela rede continua responsabilidade do gateway/integrador.

Payloads e erros clínicos ficam criptografados; hash, origem, estado e eventos de recebimento,
rejeição, aplicação e exportação permanecem auditáveis. Rotacione o segredo mediante suspeita de
vazamento e restrinja o endpoint no proxy por origem/rede quando possível.
