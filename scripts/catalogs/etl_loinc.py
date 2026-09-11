"""ETL: LOINC release oficial (LoincTable/Loinc.csv) -> formato do import_loinc do core.

Fonte: https://loinc.org/downloads/ — "LOINC Table File (CSV)". O download exige
**conta gratuita** no loinc.org; não é licença paga. A licença LOINC permite
redistribuição, mas a conta é ato de pessoa (alguém aceita os termos em nome de
alguém), então este ETL PRESSUPOE o arquivo já baixado. Ver README §LOINC.

Descartados na investigação (2026-08, registrado no README): o pacote FHIR da
RNDS não enumera nenhum código LOINC; `hl7.terminology.r4` também não; e
`tx.fhir.org/r4` só faz lookup código-a-código — serve para validar, não para dump.

Entrada: o `Loinc.csv` da release, delimitado por VÍRGULA e com campos entre
aspas (é assim que a LOINC publica). Colunas usadas: LOINC_NUM, LONG_COMMON_NAME,
COMPONENT, PROPERTY, SYSTEM, STATUS.

Saída: LOINC_NUM;LONG_COMMON_NAME;COMPONENT;PROPERTY;SYSTEM (UTF-8, ';') — que é
exatamente o que `import_loinc` espera.

Filtra STATUS != ACTIVE por padrão. LOINC marca códigos como DEPRECATED,
DISCOURAGED e TRIAL; carregar um DEPRECATED no catálogo governado é oferecer ao
usuário um código que a fonte já retirou. `--all` desliga o filtro.

Uso:
    python3 etl_loinc.py                      # procura ./Loinc.csv ou ./LoincTable/Loinc.csv
    python3 etl_loinc.py caminho/Loinc.csv
    python3 etl_loinc.py --all                # inclui não-ACTIVE

Saída em ./loinc_full.csv. A contagem sai no stderr — anote-a, é ela que vai para
`expected_rows` no manifest.toml, e o rótulo da release vai para `version`.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

CAMINHOS_PADRAO = (Path("Loinc.csv"), Path("LoincTable/Loinc.csv"))
SAIDA = Path("loinc_full.csv")
COLUNAS = ("LOINC_NUM", "LONG_COMMON_NAME", "COMPONENT", "PROPERTY", "SYSTEM")


def localizar(argv: list[str]) -> Path:
    explicitos = [a for a in argv if not a.startswith("--")]
    if explicitos:
        caminho = Path(explicitos[0])
        if not caminho.is_file():
            sys.exit(f"ETL LOINC: arquivo não encontrado: {caminho}")
        return caminho
    for candidato in CAMINHOS_PADRAO:
        if candidato.is_file():
            return candidato
    sys.exit(
        "ETL LOINC: nenhum Loinc.csv encontrado. Baixe a 'LOINC Table File (CSV)' "
        "em https://loinc.org/downloads/ (conta gratuita) e rode neste diretório, "
        "ou passe o caminho como argumento."
    )


def main(argv: list[str]) -> None:
    incluir_todos = "--all" in argv
    origem = localizar(argv)

    with origem.open(encoding="utf-8-sig", newline="") as fh:
        leitor = csv.DictReader(fh)  # vírgula + aspas, como a LOINC publica
        if leitor.fieldnames is None or "LOINC_NUM" not in leitor.fieldnames:
            sys.exit(
                f"ETL LOINC: {origem} não parece a tabela LOINC (sem coluna LOINC_NUM). "
                f"Colunas vistas: {leitor.fieldnames}"
            )

        linhas: list[tuple[str, ...]] = []
        vistos: set[str] = set()
        descartados_status = 0
        for registro in leitor:
            codigo = (registro.get("LOINC_NUM") or "").strip()
            display = (registro.get("LONG_COMMON_NAME") or "").strip()
            if not codigo or not display or codigo in vistos:
                continue
            status = (registro.get("STATUS") or "").strip().upper()
            if not incluir_todos and status and status != "ACTIVE":
                descartados_status += 1
                continue
            vistos.add(codigo)
            linhas.append(
                (
                    codigo,
                    display,
                    (registro.get("COMPONENT") or "").strip(),
                    (registro.get("PROPERTY") or "").strip(),
                    (registro.get("SYSTEM") or "").strip(),
                )
            )

    with SAIDA.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.writer(fh, delimiter=";")
        escritor.writerow(COLUNAS)
        escritor.writerows(linhas)

    print(f"ETL LOINC: {len(linhas)} códigos -> {SAIDA}", file=sys.stderr)
    if descartados_status:
        print(
            f"ETL LOINC: {descartados_status} descartados por STATUS != ACTIVE (use --all para incluir)",
            file=sys.stderr,
        )
    print(
        "ETL LOINC: anote esta contagem em expected_rows e a release em version, "
        "no scripts/catalogs/manifest.toml",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
