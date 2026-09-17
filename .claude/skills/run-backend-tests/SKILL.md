---
name: run-backend-tests
description: Roda a suíte pytest do backend do Vitali do jeito que executa o código do checkout (mount-run da imagem de dev), em vez do `docker compose exec django pytest`, que roda código velho da imagem baked e dá falso-verde. Use sempre que for rodar, reproduzir ou depurar teste de backend do Vitali.
---

# Rodar teste de backend do Vitali

## O problema que este skill existe para evitar

`docker compose exec -T django pytest` **mente**. O container `vitali-django-1` sobe de uma
imagem já construída e o bind `./backend:/app` não está ativo nele: o pytest lá dentro executa
o código que foi copiado na hora do build, não o que você acabou de editar. O resultado é o
pior tipo de verde — verde de código velho.

O jeito correto é subir um container efêmero da **imagem de dev** (`vitali-django`, a única que
tem pytest instalado; a `ghcr.io/tropeks/vitali-backend:latest` de produção não tem) montando o
`backend/` do checkout por cima de `/app`.

## Comando

Sempre a partir de `/home/rcosta00/dev/vitali`:

```bash
scripts/pytest.sh apps/pharmacy/tests/test_stockout_checker.py
```

O wrapper vive em `.claude/skills/run-backend-tests/pytest.sh` (o `scripts/pytest.sh` é o link).
Ele expande para:

```bash
sudo -n docker run --rm --network vitali_default \
  -e DJANGO_SETTINGS_MODULE=vitali.settings.development \
  -e DATABASE_URL=postgres://vitali:vitali@postgres:5432/vitali \
  -e REDIS_URL=redis://redis:6379/0 \
  -v "$PWD/backend:/app" vitali-django \
  pytest <alvo> -q --no-cov --reuse-db -p no:cacheprovider
```

Verificado em 2026-08-24: `--collect-only` coleta 3717 testes; o módulo acima passa 16/16 em 0,21s.

## Flags que importam

| Flag | Quando |
|---|---|
| `--reuse-db` | **default**. Os bancos `test_vitali*` já existem no `vitali-postgres-1`; reusar é o que torna a rodada instantânea. |
| `--create-db` | Só quando você mexeu em migration ou o schema de teste está podre. Paga o preço de recriar todos os schemas de tenant. |
| `--no-cov` | Sempre, a menos que você queira o relatório de cobertura — o plugin de cov custa segundos por rodada. |
| `-p no:cacheprovider` | Evita o `PermissionError` em `/app/.pytest_cache` (o uid do container não é dono do checkout). |
| `-x` / `-k` | Como em qualquer pytest. |

## Gotchas vizinhos

- **`makemigrations` precisa de root no container**: acrescente `-u root` ao `docker run` e depois
  `chown` o arquivo gerado de volta para `rcosta00`, senão a migration nasce pertencendo ao root.
- **Não existe `vt.sh`** neste repo, por mais que pareça que deveria.
- **Deploy carrega código real**: o `docker build` do compose canônico copia o checkout, então o
  falso-verde é problema só de *teste*, não de deploy.
- **Permissão nova em `DEFAULT_ROLES` não propaga** para tenant já provisionado: rode
  `create_default_roles --overwrite` por tenant, ou a feature nasce invisível no menu.
