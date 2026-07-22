# Redis: separação de cargas e caminho para alta disponibilidade

## Estado e objetivo

O `docker-compose.prod.yml` continua oferecendo um Redis único para compatibilidade. O overlay `docker-compose.redis-scale.yml` é opt-in e separa três papéis:

| Endpoint | Uso | Persistência |
|---|---|---|
| `redis-cache` | cache, sessão e throttling | AOF `everysec` |
| `redis` | broker Celery e Evolution API | AOF `everysec` |
| `redis-results` | resultados Celery | AOF `everysec` |

Cada processo possui volume, healthcheck, senha e usuário ACL próprios; comandos da categoria Redis `dangerous` ficam bloqueados para esses usuários. A separação reduz contenção e impede que uma limpeza de cache apague filas ou resultados.

## Limite importante

Este overlay **não é HA**. Os três processos continuam no mesmo host Docker e falham juntos se o host, disco ou rede local falhar. Sentinel com apenas um host criaria aparência de HA sem quorum ou failover real; por isso ele não é incluído.

HA real exige ao menos três failure domains para quorum ou um serviço Redis gerenciado. Nesse estágio, a aplicação já aceita endpoints independentes por `CACHE_URL`, `CELERY_BROKER_URL` e `CELERY_RESULT_BACKEND`, portanto a migração não exige alteração de código.

## Ativação

1. Use `.env.redis-scale.example` como referência e acrescente as três variáveis ao arquivo de segredos de produção já existente, por exemplo `/etc/vitali/secrets.env`.
2. Gere três segredos aleatórios diferentes, com no mínimo 32 caracteres. Mantenha também `REDIS_PASSWORD` durante a compatibilidade com o Compose base.
3. Valide a composição:

   ```bash
   docker compose \
     -f docker-compose.prod.yml \
     -f docker-compose.redis-scale.yml \
     --env-file /etc/vitali/secrets.env config --quiet
   ```

4. Suba a topologia e confirme os healthchecks:

   ```bash
   docker compose \
     -f docker-compose.prod.yml \
     -f docker-compose.redis-scale.yml \
     --env-file /etc/vitali/secrets.env up -d
   docker compose \
     -f docker-compose.prod.yml \
     -f docker-compose.redis-scale.yml ps
   ```

## Compatibilidade e rollback

Sem as variáveis específicas, o backend usa `REDIS_URL` nos três papéis. Para rollback, remova o overlay e restaure o `REDIS_URL` legado. Não remova os volumes antes de drenar filas e validar que nenhuma tarefa está pendente.

Ao migrar para Redis gerenciado, configure URLs TLS (`rediss://`) fornecidas pelo provedor e valide o comportamento de failover em staging. Sentinel exige também configuração específica dos clientes Django/Celery e quorum distribuído; não basta trocar o hostname. Cache pode aceitar perda controlada; broker e resultados exigem política de persistência, retenção, backup e RPO/RTO explícitos.
