# Onda 0 / item 0.3 — patch do gate de deploy no CI (aplicação humana)

> Preservado no repo porque o hook do Maestro (ADR-003 v1.1) mantém `.github/workflows/`
> em denylist: agentes não reescrevem workflow, nem com decision record. Este arquivo é
> documentação — a aplicação em `ci.yml` precisa ser feita por um humano.

```text
Onda 0 / item 0.3 — gate de deploy bloqueante no CI
====================================================

CONTEXTO
  backend/apps/core/checks.py:55-82 registra o system-check `core.E002`, que FALHA se
  ENFORCE_TENANT_MEMBERSHIP estiver False em producao. Ele e registrado com deploy=True,
  e `manage.py check --deploy` NAO e executado por nenhum workflow. O gate nunca dispara.
  Sem este step, um deploy futuro pode desligar a flag de novo sem deteccao automatica.

POR QUE VOCE PRECISA APLICAR (e nao um agente)
  O hook do Maestro (ADR-003 v1.1) tem .github/workflows/ em denylist: agentes nao
  reescrevem workflow, nem com decision record. O agente tentou, percebeu que estava
  contornando o controle, e reverteu. ci.yml esta intocado.

ONDE
  .github/workflows/ci.yml, job `backend-lint`, como ULTIMO step (depois de
  "Verify translation catalogs are compiled", antes da linha em branco que precede
  o comentario "# ─── Backend: Tests ───").

  Escolhido `backend-lint` e nao `backend-test` porque settings/production.py nao abre
  conexao de DB nem de cache no carregamento nem em AppConfig.ready() — so no atendimento
  real de request. Logo o check nao precisa dos services Postgres/Redis, e o feedback
  chega no job mais rapido.

APLICAR (colar exatamente, com indentacao de 6 espacos para "- name:")

      # Onda 0 / item 0.3: core.E002 (apps/core/checks.py) so roda sob --deploy.
      # Sem este step o gate de ENFORCE_TENANT_MEMBERSHIP e decorativo e um deploy
      # futuro pode desligar o isolamento multi-tenant sem deteccao.
      # Valores abaixo sao placeholders de CI, nao segredos reais.
      - name: Django deploy checks (multi-tenant isolation gate)
        env:
          DJANGO_SETTINGS_MODULE: vitali.settings.production
          ENVIRONMENT: production
          DEPLOYMENT_PROFILE: pool
          ENFORCE_TENANT_MEMBERSHIP: "true"
          SECRET_KEY: ci-placeholder-not-a-real-secret-key-000000000000
          ALLOWED_HOSTS: example.com
          DATABASE_URL: postgres://vitali:vitali@127.0.0.1:5432/vitali
          POSTGRES_PASSWORD: ci-placeholder
          REDIS_PASSWORD: ci-placeholder
          WHATSAPP_EVOLUTION_API_KEY: ci-placeholder
          FIELD_ENCRYPTION_KEY: ci-placeholder-fernet-key-REPLACE
        run: python manage.py check --deploy

NOTAS DE APLICACAO
  1. FIELD_ENCRYPTION_KEY precisa ser uma chave Fernet VALIDA (44 chars base64url), nao o
     placeholder acima — assert_field_encryption_key em vitali/settings/_security_checks.py
     rejeita o placeholder zero. Gere uma descartavel so para o CI:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     Essa chave NAO cifra nada em CI (nenhum dado e gravado); ainda assim, prefira coloca-la
     como secret do repositorio em vez de literal no YAML.
  2. NAO adicionar `|| true` nem `continue-on-error`. O repositorio hoje esta limpo desses
     anti-padroes (verificado: zero ocorrencias em ci.yml) e o valor do gate depende disso.
  3. Se o step falhar por warnings de seguranca do Django (W004/W008/W012/W016/W018/W019):
     nao deveria acontecer, porque production.py ja hardcoda SECURE_HSTS_*, SECURE_SSL_REDIRECT,
     SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, DEBUG=False e X_FRAME_OPTIONS. Se acontecer,
     investigue o warning especifico — NAO enfraqueca o gate com --fail-level nem com skip
     generico. Se precisar restringir, use `--tag security` ou silencie o ID especifico via
     SILENCED_SYSTEM_CHECKS, documentando o porque.

VALIDAR ANTES DE COMMITAR
     python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
  e, dentro do container django:
     python manage.py check --deploy

PROVA DE QUE O GATE FUNCIONA
  Depois de aplicado, rode uma vez com ENFORCE_TENANT_MEMBERSHIP: "false" no env do step.
  O job DEVE ficar vermelho com core.E002. Se ficar verde, o gate nao esta pegando e o step
  precisa ser revisto. Volte para "true" depois do teste.
```
