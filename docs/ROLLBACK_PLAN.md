# Go-Live Rollback Plan

Este documento detalha os procedimentos de rollback em caso de falha crítica durante ou imediatamente após o Go-Live de um novo tenant (Piloto ou GA).

## 1. Gatilhos para Rollback
- Corrupção de dados durante a importação inicial (pacientes, profissionais).
- Falhas críticas de compliance causadas por wedges (ex: geração de TISS inválida).
- Impossibilidade de realizar operações clínicas básicas (prontuário, prescrição).
- Degradação de performance global que afete outros tenants.

## 2. Ações Imediatas (Primeiros 15 minutos)
1. **Comunicação**: Notificar os administradores da clínica que o sistema passará por um rollback e ficará indisponível temporariamente.
2. **Interrupção de Tráfego**: Redirecionar o DNS do tenant para uma página de manutenção estática.
3. **Bloqueio de Acesso**: Desativar o tenant no banco de dados para evitar novas escritas:
   ```bash
   docker compose exec django python manage.py shell -c "from apps.core.models import Tenant; t = Tenant.objects.get(schema_name='<schema_name>'); t.status = 'suspended'; t.save()"
   ```

## 3. Reversão de Dados (Banco de Dados)
- Se a corrupção ocorreu durante o provisionamento ou importação inicial, o schema do tenant deve ser dropado:
   ```bash
   docker compose exec django python manage.py shell -c "from apps.core.models import Tenant; t = Tenant.objects.get(schema_name='<schema_name>'); t.delete(force_drop=True)"
   ```
- *Nota: `django-tenants` remove o schema PostgreSQL quando `force_drop=True` é acionado.*

## 4. Rollback de Código
- Caso o Go-Live tenha incluído um deploy com falhas críticas não isoladas, reverter para a versão anterior:
   ```bash
   git checkout <previous_stable_tag>
   docker compose build
   docker compose up -d
   ```
- Rodar `scripts/migrate_schemas.sh` para assegurar que as tabelas do schema public estejam na versão correta.

## 5. Pós-Rollback
1. Executar `scripts/smoke_test.sh` no ambiente de staging/produção para confirmar que o sistema voltou à estabilidade.
2. Atualizar o cliente sobre a conclusão do rollback e agendar nova janela de Go-Live.
3. Realizar um post-mortem para investigar a causa-raiz e mitigar recorrências.
