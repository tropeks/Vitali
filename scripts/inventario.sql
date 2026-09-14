-- Inventário do banco — fonte ÚNICA da comparação do drill (ordem 012).
--
-- Vivia só no disco da lab (`migracao/inventario.sql`), fora do versionamento, e era
-- comparado contra uma FOTO ESTÁTICA de 11/09 — o que fazia a fase 2 do drill divergir
-- sempre e nunca poder reprovar. Agora o `backup.sh` roda este mesmo SQL no instante do
-- `pg_dump`, ao lado do artefato, e o drill compara o restore contra essa foto: a única
-- que descreve o mesmo instante que o dump.
--
-- Contagem exata por `count(*)` via `query_to_xml`, não estimativa de `reltuples`:
-- estimativa não serve para provar que um restore trouxe o que a origem tinha.

\echo '### SCHEMAS'
SELECT nspname FROM pg_namespace
WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
ORDER BY 1;

\echo '### TENANTS (public.core_tenant)'
SELECT * FROM public.core_tenant ORDER BY id;

\echo '### DOMINIOS (public.core_domain)'
SELECT * FROM public.core_domain ORDER BY id;

\echo '### CONTAGEM EXATA DE LINHAS, TODA TABELA DE TODO SCHEMA'
SELECT table_schema, table_name,
       (xpath('/row/cnt/text()',
              query_to_xml(format('select count(*) as cnt from %I.%I', table_schema, table_name),
                           false, true, '')))[1]::text::bigint AS linhas
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2;

\echo '### TOTAL GERAL'
SELECT count(*) AS tabelas,
       sum((xpath('/row/cnt/text()',
            query_to_xml(format('select count(*) as cnt from %I.%I', table_schema, table_name),
                         false, true, '')))[1]::text::bigint) AS linhas_totais
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema');
