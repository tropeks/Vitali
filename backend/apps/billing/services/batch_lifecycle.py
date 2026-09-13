"""Ciclo de vida do lote TISS — hoje só o fechamento (ordem 008).

**Por que isto existe.** O fechamento de lote vivia inteiro dentro de
``TISSBatchViewSet.close``, devolvendo ``Response`` de dentro do ``transaction.atomic()``.
Regra de negócio vestida de HTTP: quem não fala HTTP não consegue fechar lote. Foi o que
travou a cadeia de receita — ``verify_revenue_chain`` somava os itens em memória e
imprimia o número, deixando o lote ``open`` com ``total_value`` em 0,00, porque o caminho
que grava estava inacessível a um management command.

Segue o padrão que o ``billing`` já usa para transição de estado
(``services/aih_lifecycle.py``): função de módulo com ``@transaction.atomic``, argumentos
por palavra-chave, ``select_for_update``, exceção tipada para cada recusa, e o objeto de
volta. Quem traduz para status HTTP é a view, e só ela.

**O que NÃO mudou na mudança:** cada comentário abaixo registra um defeito que já
aconteceu — a ordem dos locks, o conjunto de ids capturado uma única vez, a reafirmação de
pertencimento antes de finalizar e a soma escopada em ``evaluated_ids``. Eles vieram
junto porque a razão de existirem veio junto.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import TISSBatch


class FechamentoRecusado(Exception):
    """Base das recusas de fechamento. A view mapeia cada subclasse para um status."""


class LoteNaoAberto(FechamentoRecusado):
    """O lote não está ``open`` — fechar de novo não é operação válida. View: 400."""

    def __init__(self, status_atual: str) -> None:
        self.status_atual = status_atual
        super().__init__(f"Batch is already '{status_atual}', cannot close.")


class GlosaBloqueante(FechamentoRecusado):
    """Há guia com alerta de glosa BLOQUEANTE não reconhecido. View: 409.

    Carrega o ``blocking`` cru — ``[(guide, [alert, ...]), ...]`` — e não o corpo já
    montado. O formato do 409 é contrato HTTP e continua sendo decidido na view: o
    service diz *o que* aconteceu, não *como* se escreve para o cliente.
    """

    def __init__(self, blocking: list[tuple[Any, list[Any]]]) -> None:
        self.blocking = blocking
        super().__init__("Lote tem guia com alerta de glosa bloqueante em aberto.")


class LoteAlteradoDuranteFechamento(FechamentoRecusado):
    """O conjunto de guias mudou entre a avaliação e a finalização. View: 409."""

    def __init__(self) -> None:
        super().__init__("O lote foi modificado durante o fechamento; reavalie e feche novamente.")


def fechar_lote(*, lote: TISSBatch, actor: Any) -> TISSBatch:
    """Fecha o lote: grava ``status``, ``closed_at`` e ``total_value``, e submete as guias.

    Devolve a instância travada e já atualizada. Levanta ``LoteNaoAberto``,
    ``GlosaBloqueante`` ou ``LoteAlteradoDuranteFechamento`` para as recusas, e deixa
    subir a ``ValidationError`` do modelo quando uma guia já foi apresentada em outro
    lote finalizado — essa é do domínio, não deste caminho.
    """
    if lote.status != "open":
        raise LoteNaoAberto(lote.status)

    locked_batch, recusa = _tentar_fechar(lote=lote, actor=actor)
    # A recusa vira exceção AQUI FORA, depois que a transação comitou.
    #
    # Levantá-la lá dentro reverteria o bloco — e o que o bloco escreveu antes de
    # recusar são os ALERTAS DE GLOSA que a avaliação acabou de persistir. A view
    # original saía por `return Response(...)`, que fecha o `with` normalmente e
    # comita; trocar isso por `raise` apagava os alertas junto, e o 409 passava a
    # devolver ao cliente o id de uma linha que não existia mais — o
    # `acknowledge` seguinte respondia 404.
    #
    # Quem pegou foi `test_acknowledge_block_then_reclose_succeeds`, que já estava
    # escrito, nas quatro classes de `test_glosa_safety.py`. Era o oráculo desta
    # extração e funcionou como tal.
    if recusa is not None:
        raise recusa
    return locked_batch


@transaction.atomic
def _tentar_fechar(*, lote: TISSBatch, actor: Any) -> tuple[TISSBatch, FechamentoRecusado | None]:
    """A tentativa transacional: devolve ``(lote travado, recusa ou None)``.

    Devolve a recusa em vez de levantá-la porque sair do bloco pelo `return` comita
    o que a avaliação gravou, e levantar reverteria. A fronteira desta função é
    exatamente o alcance do lock de linha: tudo aqui dentro precisa do mesmo lock,
    e nada aqui dentro faz sentido fora dele.
    """
    # TOCTOU fix: lock the BATCH row first, then read its guide set from
    # the locked instance. Without the batch lock a concurrent
    # guides.add(new_guide) could slip an UNEVALUATED guide into the
    # batch between evaluation and the blocking-check (which reads
    # batch.guides.all()), letting an un-checked guide through the gate.
    # We evaluate exactly locked_batch.guides.all() and then run the
    # blocking-check over that SAME locked instance, so no guide can be
    # present-but-unevaluated.
    locked_batch = TISSBatch.objects.select_for_update().get(pk=lote.pk)

    # Re-validate double-submit at close time. Two batches can both be
    # left "open" with the same guide (the serializer/signal checks ran
    # while both were open and saw no *finalised* conflict); without this
    # re-check, closing both would export the guide in two XMLs → billed
    # twice (financial + ANS violation). Lock the candidate guides so a
    # concurrent close of a sibling batch cannot race past this check.
    #
    # Capture the guide id set ONCE under the batch-row lock. This is the
    # SET OF RECORD for the rest of the close: we evaluate exactly these
    # guides AND run the blocking-check over exactly these ids, so no
    # guide can be present-but-unevaluated. A membership re-assertion just
    # before finalize closes the add-after-capture window.
    locked_guides = list(locked_batch.guides.select_for_update())
    evaluated_ids = [g.pk for g in locked_guides]
    for guide in locked_guides:
        # Only finalised batches (closed/submitted) constitute a real
        # double-billing conflict at this point; another still-open
        # batch holding the same guide is fine — whichever closes
        # first wins, and the second close will then be rejected here.
        # Cancelled batches never conflict.
        locked_batch.check_guide_not_double_submitted(guide, statuses=["closed", "submitted"])

    # Glosa-safety soft-stop (wedge PR G1). No-op when the glosa_safety
    # feature flag is OFF for this tenant — gate behaves exactly as
    # before. PER-GUIA: evaluate each guide under the lock, then refuse with
    # ONLY the offending guides if any has an unacknowledged BLOCKING
    # alert. The faturista removes/acknowledges those guides and
    # re-closes; we do NOT close the batch nor block the clean guides.
    from .glosa_safety import GlosaSafetyService

    glosa_service = GlosaSafetyService(requesting_user=actor)
    # Evaluate exactly the captured guide-id set...
    for guide in locked_guides:
        glosa_service.evaluate_guide(guide, gate="batch_close")
    # ...and check blocking alerts over the SAME id set (NOT a fresh
    # batch.guides.all() re-query), so the evaluated set and the checked
    # set are provably identical — a guide cannot be
    # present-but-unevaluated between the two steps.
    blocking = glosa_service.blocking_glosa_alerts_for_guides(evaluated_ids)
    if blocking:
        return locked_batch, GlosaBloqueante(blocking)

    # Membership re-assertion: immediately before finalizing (batch row
    # still locked, same atomic block), re-read the batch's current guide
    # set. If it differs from the set we evaluated, a guide was
    # added/removed mid-close — finalizing now would close a
    # present-but-unevaluated guide. Refuse instead; the faturista
    # re-closes and the new set is re-evaluated.
    current_ids = set(locked_batch.guides.values_list("pk", flat=True))
    if current_ids != set(evaluated_ids):
        return locked_batch, LoteAlteradoDuranteFechamento()

    # Finalize STRICTLY over the evaluated id set — never re-query the
    # `.guides` relation here. Under READ COMMITTED a concurrent
    # guides.add() can commit between the re-assertion above and these
    # writes (Postgres FK FOR KEY SHARE does not conflict with the batch
    # row's FOR NO KEY UPDATE lock); a fresh `.guides` query would then
    # phantom-read that guide and bill/submit it WITHOUT it ever being
    # evaluated. Scoping to evaluated_ids makes that impossible: only the
    # guides we actually evaluated are summed and submitted.
    total = locked_batch.guides.filter(pk__in=evaluated_ids).aggregate(total=Sum("total_value"))[
        "total"
    ] or Decimal("0")
    locked_batch.status = "closed"
    locked_batch.closed_at = timezone.now()
    locked_batch.total_value = total
    locked_batch.save(update_fields=["status", "closed_at", "total_value"])
    locked_batch.guides.filter(pk__in=evaluated_ids, status="pending").update(status="submitted")
    return locked_batch, None
