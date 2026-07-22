# RabbitMQ para Celery em produção

O Vitali continua usando Redis por padrão. O RabbitMQ é uma opção explícita de
produção e não substitui o Redis usado por cache, sessões e, por padrão, pelos
resultados do Celery.

## Configuração

Defina no arquivo de segredos do host:

```dotenv
RABBITMQ_USER=vitali
RABBITMQ_PASSWORD=<senha-URL-safe-forte>
RABBITMQ_VHOST=vitali
CELERY_BROKER_URL=amqp://vitali:<senha-URL-encoded>@rabbitmq:5672/vitali
# Opcional; o padrão do overlay mantém resultados no Redis.
CELERY_RESULT_BACKEND=redis://:<senha-redis-URL-encoded>@redis:6379/0
```

Usuário, senha e vhost são provisionados somente no primeiro boot do volume.
Alterar essas variáveis depois exige rotacionar a credencial dentro do RabbitMQ;
não remova o volume para fazer rotação em produção.

Suba e valide o overlay:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.rabbitmq.yml \
  --env-file /etc/vitali/secrets.env config --quiet
docker compose -f docker-compose.prod.yml -f docker-compose.rabbitmq.yml \
  --env-file /etc/vitali/secrets.env up -d
docker compose -f docker-compose.prod.yml -f docker-compose.rabbitmq.yml ps
```

O volume `rabbitmq_data` torna mensagens e metadados duráveis entre reinícios. As
filas são declaradas pelo Celery e separadas em `critical`, `default` e `bulk`.
O worker do overlay consome as três; em escala, pode-se iniciar pools separados
com `-Q critical`, `-Q default` e `-Q bulk`.

## Semântica de entrega

No overlay, `acks_late`, rejeição quando o processo morre e prefetch 1 favorecem
redelivery. Portanto as tasks devem permanecer idempotentes: RabbitMQ/Celery
oferecem entrega pelo menos uma vez, não exatamente uma vez. Os limites padrão
são 270 segundos (soft) e 300 segundos (hard); aumente-os apenas por task quando
o trabalho for comprovadamente longo.

O management UI da imagem não publica porta no host. Se acesso operacional for
necessário, exponha-o apenas em loopback/VPN e aplique RBAC próprio do RabbitMQ.
