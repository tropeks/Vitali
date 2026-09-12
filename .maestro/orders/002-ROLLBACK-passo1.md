<!-- maestro-order v1
absorbed_by: 002
-->
> **Absorvido pela ordem 002.** Este documento registrou o estado da lab antes do passo 1
> e serviu de caminho de volta. O rollback **foi executado** — a primeira tentativa caiu no
> guard de boot da `BACKUP_ENCRYPTION_KEY` e voltou por aqui — e depois foi **superado** pelo
> passo 1 refeito com a chave provisionada. Não é ordem: não tem aceite nem recibo, e o
> `maestro order --list` só o enxergava assim por ele morar no diretório das ordens.

# Rollback — ordem 002, passo 1

Estado da lab **antes** do build do HEAD. Registrado em 2026-09-11, como condição (1) do
Imediato. Para desfazer, é isto que volta.

| Serviço | Referência | Config digest |
|---|---|---|
| `django`, `celery-worker`, `celery-beat` | `ghcr.io/tropeks/vitali-backend@sha256:da58aae3e49a394b56381de19d79ce65d26eae8c3b4bd968f3e8574fbfcb5441` | `0f44e312358d` |
| `vitali-viewer` | `ghcr.io/tropeks/vitali-viewer@sha256:62c43e2c8fb5810e7a50d0550f15e13c6a1222317fe85389d052b9a44858b020` | `c8042d6b0a3f` |
| `nextjs` | **sem digest de registry** — imagem local `ghcr.io/tropeks/vitali-frontend:latest` | `cad2465ead86` |

O frontend é o caso especial: ele nunca veio de registry. Se for sobrescrito, o caminho de
volta é o tarball preservado na própria lab:

```bash
gunzip -c /srv/vulcan/apps/vitali/migracao/img-vitali-frontend.tar.gz | docker load
# sha256 do tarball: b622861387b64242a25f38a0496d9d38ee7fc21f9a824da3342aa0c9128f4e33
```

## Como desfazer

Editar os `image:` do `docker-compose.lab.yml` de volta para os digests acima e:

```bash
cd /srv/vulcan/apps/vitali
docker compose -p vitali-lab -f docker-compose.staging.yml -f docker-compose.lab.yml \
  --env-file .env.staging --profile backup up -d
```

**Os volumes não são tocados por nenhum dos dois sentidos.** O banco restaurado, o
`orthanc_data` e o `backups` continuam onde estão; só as imagens trocam. Volta em um minuto.

## Verificação depois do rollback

```bash
COMPOSE_PROJECT_NAME=vitali-lab BASE_URL=https://vitali.qtec.me \
COMPOSE_FILE=docker-compose.staging.yml COMPOSE_ENV_FILE=.env.staging \
  bash scripts/smoke_test.sh     # tem de voltar a 8/8
```

Lembrete medido: o `login` tem throttle de **5/min**. Duas execuções seguidas do smoke dão
429 no teste de credencial errada — espere a janela antes de concluir que quebrou.
