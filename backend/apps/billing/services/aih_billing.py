"""
AI2 — Bridge de faturamento SUS de internação (Admission → AIH).
================================================================
Quando uma internação (:class:`~apps.emr.adt_models.Admission`) recebe alta,
materialise uma :class:`~apps.billing.sus_models.AihAutorizacao` (Autorização de
Internação Hospitalar / SISAIH) valorada por SIGTAP no eixo SH+SP. É o análogo
hospitalar do bridge ambulatorial APAC/BPA-I
(:mod:`apps.billing.services.sus_production`) e da ponte cirúrgica
(:mod:`apps.billing.services.surgery_billing`): o domínio clínico
(``apps.emr``) nunca importa billing, então a ponte vive aqui e lê
``Admission``/``EncounterProcedure`` diretamente.

Contrato (documentado — a ponte preenche lacunas honestamente, NUNCA fabrica
dados clínicos nem inventa o código de faturamento):

  * **Pré-condições**: a internação precisa estar com **alta**
    (``status == DISCHARGED``) e ter ``actual_discharge_datetime`` preenchido — a
    AIH fatura na alta, jamais fabricamos uma data de saída. O
    ``procedimento_principal`` (SIGTAP) é **obrigatório**: é uma decisão de
    codificação SUS do faturista, não se adivinha o principal.

  * **Auto-preenchimento da internação**: ``data_internacao`` e ``data_saida``
    vêm das datas da internação; ``patient`` e ``professional_responsavel``
    (= ``attending_professional``) idem; ``cns`` é um snapshot em texto do CNS do
    paciente no momento da geração (``Patient.cns`` é encriptado/não-queryável —
    mesmo racional do snapshot de APAC/BPA-I).

  * **Mapeamento de caráter** (``admission_source`` → ``carater_internacao``):

        EMERGENCIA            → URGENCIA ("02")
        AMBULATORIO           → ELETIVO  ("01")
        CENTRO_CIRURGICO      → ELETIVO  ("01")
        TRANSFERENCIA_EXTERNA → ELETIVO  ("01")   (default — sem sinal de urgência)
        OUTRO                 → ELETIVO  ("01")   (default)

  * **Mapeamento de motivo de saída** (``disposition`` → ``motivo_saida``):

        ALTA_MELHORADA        → ALTA_MELHORADO
        ALTA_A_PEDIDO         → ALTA_MELHORADO   (desfecho de alta mais próximo)
        TRANSFERENCIA_EXTERNA → TRANSFERENCIA
        OBITO                 → OBITO
        EVASAO                → PERMANENCIA       (não é alta formal — permanência)
        OUTRO                 → PERMANENCIA       (desfecho indefinido — permanência)
        (sem disposition)     → "" (em branco — internação sem desfecho registrado)

  * **numero_aih**: se informado, é usado como está (o número oficial é emitido
    pelo gestor SUS). Se ausente, geramos um número **provisório interno** no
    padrão ``YYYYMM`` + sequência de 7 dígitos (espelha
    ``TISSGuide.generate_guide_number``), válido até a remessa SISAIH (AI3)
    substituí-lo pelo número oficial.

  * **Secundários**: se ``secundarios`` (lista de ``(sigtap, quantidade)``) for
    passado, é usado. Senão, auto-puxa os ``EncounterProcedure`` do
    ``admission.encounter`` que tenham ``sigtap`` preenchido E sejam diferentes do
    ``procedimento_principal`` — um ``AihProcedimentoSecundario`` por linha
    (quantidade = ``int(EncounterProcedure.quantity)``). Sem encounter → sem
    secundários (nunca fabricamos procedimentos).

  * **Valoração**: o ``valor`` do header = ``(principal.valor_sh +
    principal.valor_sp)`` + soma dos ``valor`` dos secundários (que já computam
    ``(valor_sh + valor_sp) × qtd`` no próprio ``save``). AIH usa o eixo **SH+SP**
    (serviços hospitalares + profissionais), diferente do SA+SP ambulatorial.

  * **Idempotente**: no máximo uma AIH por internação (``UniqueConstraint``
    parcial ``uniq_aih_per_admission`` faz o backstop). Uma 2ª chamada devolve a
    AIH já existente, sem duplicar.

``apps.billing → apps.emr`` é a mesma aresta grandfathered que os bridges
ambulatorial/cirúrgico já usam.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.sus_models import AihAutorizacao, AihProcedimentoSecundario, SusCompetencia
from apps.emr.adt_models import Admission
from apps.emr.models import EncounterProcedure

# ── Tabelas de mapeamento (documentadas no docstring do módulo) ───────────────
# Chaves/valores são membros TextChoices (subclasses de str); anotamos como
# ``dict[str, str]`` para o ``.get(campo_str, ...)`` casar no mypy.
_CARATER_POR_ORIGEM: dict[str, str] = {
    Admission.AdmissionSource.EMERGENCIA: AihAutorizacao.CaraterInternacao.URGENCIA,
    Admission.AdmissionSource.AMBULATORIO: AihAutorizacao.CaraterInternacao.ELETIVO,
    Admission.AdmissionSource.CENTRO_CIRURGICO: AihAutorizacao.CaraterInternacao.ELETIVO,
    Admission.AdmissionSource.TRANSFERENCIA_EXTERNA: AihAutorizacao.CaraterInternacao.ELETIVO,
    Admission.AdmissionSource.OUTRO: AihAutorizacao.CaraterInternacao.ELETIVO,
}

_MOTIVO_POR_DESFECHO: dict[str, str] = {
    Admission.Disposition.ALTA_MELHORADA: AihAutorizacao.MotivoSaida.ALTA_MELHORADO,
    Admission.Disposition.ALTA_A_PEDIDO: AihAutorizacao.MotivoSaida.ALTA_MELHORADO,
    Admission.Disposition.TRANSFERENCIA_EXTERNA: AihAutorizacao.MotivoSaida.TRANSFERENCIA,
    Admission.Disposition.OBITO: AihAutorizacao.MotivoSaida.OBITO,
    Admission.Disposition.EVASAO: AihAutorizacao.MotivoSaida.PERMANENCIA,
    Admission.Disposition.OUTRO: AihAutorizacao.MotivoSaida.PERMANENCIA,
}


def _mapear_carater(admission_source: str) -> str:
    """Mapeia ``Admission.AdmissionSource`` → caráter da internação (default ELETIVO)."""
    return _CARATER_POR_ORIGEM.get(admission_source, AihAutorizacao.CaraterInternacao.ELETIVO)


def _mapear_motivo_saida(disposition: str | None) -> str:
    """Mapeia ``Admission.Disposition`` → motivo de saída (sem desfecho → em branco)."""
    if not disposition:
        return ""
    return _MOTIVO_POR_DESFECHO.get(disposition, AihAutorizacao.MotivoSaida.PERMANENCIA)


def _gerar_numero_aih_provisorio() -> str:
    """Número AIH provisório interno: ``YYYYMM`` + sequência de 7 dígitos.

    Espelha ``TISSGuide.generate_guide_number``. Provisório até a remessa SISAIH
    (AI3) receber o número oficial do gestor SUS. Deve rodar dentro de um bloco
    atômico com ``select_for_update``.
    """
    prefix = timezone.now().strftime("%Y%m")
    last = (
        AihAutorizacao.objects.select_for_update()
        .filter(numero_aih__startswith=prefix)
        .order_by("-numero_aih")
        .first()
    )
    seq = int(last.numero_aih[6:]) + 1 if last and last.numero_aih[6:].isdigit() else 1
    return f"{prefix}{seq:07d}"


def _valor_principal(sigtap) -> Decimal:
    """Valor do procedimento principal no eixo hospitalar: ``valor_sh + valor_sp``."""
    sh = sigtap.valor_sh if sigtap.valor_sh is not None else Decimal("0")
    sp = sigtap.valor_sp if sigtap.valor_sp is not None else Decimal("0")
    return sh + sp


def generate_aih_for_admission(
    admission: Admission,
    competencia: SusCompetencia,
    *,
    procedimento_principal,
    secundarios=None,
    numero_aih: str | None = None,
) -> AihAutorizacao:
    """Gera (ou devolve a existente) AIH de uma internação com alta.

    Atômico + idempotente. Levanta ``django.core.exceptions.ValidationError``
    (→ 400 na view) quando a internação não está com alta, sem
    ``actual_discharge_datetime`` ou sem ``procedimento_principal``. Uma 2ª
    chamada devolve a AIH criada pela primeira (não duplica).

    Parameters
    ----------
    admission:
        A internação âncora (precisa estar ``DISCHARGED`` com alta efetiva).
    competencia:
        Competência SUS onde a AIH é registrada.
    procedimento_principal:
        Instância ``core.SIGTAPProcedure`` — decisão de codificação SUS
        (obrigatória, nunca inferida).
    secundarios:
        Opcional, lista de ``(sigtap, quantidade)``. Ausente → auto-puxa do
        encounter da internação.
    numero_aih:
        Opcional. Ausente → gera número provisório interno.
    """
    with transaction.atomic():
        # ``of=("self",)`` restringe o FOR UPDATE à linha da Admission: um
        # select_related do ``encounter`` (nullable) vira LEFT OUTER JOIN e o
        # Postgres recusa FOR UPDATE no lado nullable de um outer join.
        adm = (
            Admission.objects.select_for_update(of=("self",))
            .select_related("patient", "attending_professional", "encounter")
            .get(pk=admission.pk)
        )

        # Idempotência: já existe AIH para esta internação → devolve sem duplicar.
        existing = AihAutorizacao.objects.filter(admission=adm).first()
        if existing is not None:
            return existing

        # ── Pré-condições (mensagens pt-BR claras) ────────────────────────────
        if procedimento_principal is None:
            raise ValidationError(
                "Procedimento principal (SIGTAP) é obrigatório — é decisão de "
                "codificação SUS e não pode ser inferido."
            )
        if adm.status != Admission.Status.DISCHARGED:
            raise ValidationError(
                "Somente internações com alta (discharged) podem gerar AIH "
                f"(status atual: {adm.status})."
            )
        if adm.actual_discharge_datetime is None:
            raise ValidationError(
                "Internação sem data de alta efetiva — a AIH fatura na alta e não "
                "fabrica data de saída."
            )

        cns = (getattr(adm.patient, "cns", "") or "").strip()

        # ── Header (valor preenchido depois de somar os secundários) ──────────
        numero = numero_aih or _gerar_numero_aih_provisorio()
        aih = AihAutorizacao(
            competencia=competencia,
            numero_aih=numero,
            admission=adm,
            procedimento_principal=procedimento_principal,
            patient=adm.patient,
            cns=cns,
            professional_responsavel=adm.attending_professional,
            data_internacao=adm.admission_datetime.date(),
            data_saida=adm.actual_discharge_datetime.date(),
            carater_internacao=_mapear_carater(adm.admission_source),
            motivo_saida=_mapear_motivo_saida(adm.disposition),
            valor=Decimal("0"),
        )
        # Só geramos número provisório em retry; um número explícito colidindo é
        # erro do chamador e deve propagar.
        if numero_aih is not None:
            aih.save()
        else:
            for _attempt in range(3):
                try:
                    with transaction.atomic():
                        aih.save()
                    break
                except IntegrityError:
                    aih.numero_aih = _gerar_numero_aih_provisorio()
            else:
                raise IntegrityError(
                    "Não foi possível gerar um número AIH provisório único após 3 tentativas."
                )

        # ── Secundários ───────────────────────────────────────────────────────
        total_secundarios = Decimal("0")
        if secundarios is None:
            secundarios = _secundarios_do_encounter(adm, procedimento_principal)
        for sigtap, quantidade in secundarios:
            sec = AihProcedimentoSecundario.objects.create(
                aih=aih, sigtap=sigtap, quantidade=int(quantidade)
            )
            total_secundarios += sec.valor

        # ── Valoração do header: principal (SH+SP) + soma dos secundários ─────
        aih.valor = _valor_principal(procedimento_principal) + total_secundarios
        aih.save(update_fields=["valor"])
        return aih


def _secundarios_do_encounter(admission: Admission, procedimento_principal) -> list[tuple]:
    """Auto-puxa ``(sigtap, quantidade)`` do encounter da internação.

    Só ``EncounterProcedure`` com ``sigtap`` preenchido E diferente do
    ``procedimento_principal``. Sem encounter → lista vazia.
    """
    if admission.encounter_id is None:
        return []
    eps = (
        EncounterProcedure.objects.select_related("sigtap")
        .filter(encounter_id=admission.encounter_id, sigtap__isnull=False)
        .exclude(sigtap_id=procedimento_principal.pk)
        .order_by("created_at")
    )
    linhas = [(ep.sigtap, int(ep.quantity)) for ep in eps]

    # B7 — as cirurgias executadas da internação também são procedimentos SUS
    # desta AIH. Antes ficavam de fora e o ato cirúrgico não era faturado.
    from apps.billing.services.surgery_sus import surgical_sigtap_lines

    linhas += [
        (sigtap, qtd)
        for sigtap, qtd in surgical_sigtap_lines(admission)
        if sigtap.pk != procedimento_principal.pk
    ]
    return linhas
