"""Reusable DRF view mixins."""

import logging

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class AuditReadMixin:
    """Log read access to the immutable AuditLog — CFM Res. 1.821/2007 requires
    traceability of access to clinical records, not just changes.

    ``retrieve`` (single-record reads) is ALWAYS logged as ``view_record``,
    carrying the resource id. Set ``audit_resource_type`` on the viewset to
    the name recorded in the trail (e.g. "Patient", "Encounter").

    ``list`` is logged as ``view_record_list`` ONLY when the request carries a
    targeted lookup (``?patient=`` or ``?search=``) — i.e. when a user is
    hunting for a specific chart rather than browsing a routine worklist.
    An unfiltered ``list`` (e.g. today's appointment board) is NOT logged:
    it would put one row in the trail per page view of a normal work screen,
    drowning the signal without adding traceability value. What's recorded is
    the search CRITERION (the patient id or the search term), never the
    result set — the trail answers "what did this user go looking for", not
    "what PHI did the response contain" (see AuditTrailViewSet in
    views_audit.py for why the response side matters: it must not itself leak
    ``old_data``/``new_data``).

    ``AUDIT_LIST_ALWAYS`` (ordem 019, opt-in, default ``False``) inverte essa
    regra por viewset: quando ``True``, ``list`` grava SEMPRE, com ou sem
    critério. É para as views onde o próprio LISTAR já é o acesso sensível —
    ``PatientViewSet.list`` devolve o rol de pacientes (nome, prontuário), e
    hoje passear por ele sem filtro não deixa rastro nenhum (medido em 57 dias
    de staging: só ``retrieve`` gravou algo). O default continua ``False``
    porque, para a maioria das views, uma listagem sem filtro é tela de
    trabalho normal (ver ``ACTIONS_ISENTAS`` em ``audit_coverage.py`` para as
    coletivas que fazem polling) — ligar isto em toda view custaria volume sem
    trazer sinal.

    ``AUDIT_READ_ACTIONS`` (ordem 019, item 2) estende a mesma trilha a
    ``@action`` de detalhe que leem prontuário — ``PatientViewSet.timeline``,
    ``.allergies``, ``.medical_history``, ``.insurance``,
    ``EncounterViewSet.procedures``, ``SurgicalCaseViewSet.timeline``,
    ``TISSBatchViewSet.download`` — que ``retrieve``/``list`` não interceptam
    porque não são ``retrieve`` nem ``list``. A lista é DECLARATIVA de
    propósito: ``apps.core.audit_coverage`` precisa ENUMERAR quais rotas GET
    de uma view estão cobertas sem executar a view, e um decorador por método
    não dá isso a ler — só um atributo de classe dá. Cada nome em
    ``AUDIT_READ_ACTIONS`` grava ``view_record`` (mesma ação de ``retrieve``)
    quando o método é GET e a resposta é 2xx, usando o mesmo lookup de
    ``retrieve`` para o ``resource_id`` (essas actions são todas
    ``detail=True``, penduradas no id do recurso pai) — o nome da action
    específica vai em ``new_data`` para não perder qual sub-recurso foi lido.
    """

    audit_resource_type: str | None = None

    #: Query params whose presence turns a ``list`` into a targeted lookup.
    AUDIT_LIST_PARAMS: tuple[str, ...] = ("patient", "search")

    #: Ordem 019, item 1 — ver docstring da classe.
    AUDIT_LIST_ALWAYS: bool = False

    #: Ordem 019, item 2 — ver docstring da classe. Nomes de ``@action``
    #: (``self.action``, o nome que o Router do DRF já usa) que devem gravar
    #: leitura mesmo não sendo ``retrieve``/``list``.
    AUDIT_READ_ACTIONS: frozenset[str] = frozenset()

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            lookup = self.lookup_url_kwarg or self.lookup_field
            self._log_audit_event(request, "view_record", kwargs.get(lookup))
        return response

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            criteria = {
                param: request.query_params[param]
                for param in self.AUDIT_LIST_PARAMS
                if request.query_params.get(param)
            }
            if criteria or self.AUDIT_LIST_ALWAYS:
                self._log_audit_event(
                    request, "view_record_list", criteria.get("patient", ""), new_data=criteria
                )
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        """Fecha a lacuna que a ordem 019 mediu: ``@action`` de detalhe que lê
        prontuário (``medical_history``, ``download`` do lote TISS etc.) não
        passa por ``retrieve``/``list`` — o DRF despacha direto para o método
        da action. ``finalize_response`` roda para TODA resposta, então é o
        único lugar comum onde interceptar sem repetir o log em cada método.
        """
        response = super().finalize_response(request, response, *args, **kwargs)
        action = getattr(self, "action", None)
        if (
            action in self.AUDIT_READ_ACTIONS
            and request.method == "GET"
            and 200 <= response.status_code < 300
        ):
            lookup = self.lookup_url_kwarg or self.lookup_field
            self._log_audit_event(
                request, "view_record", kwargs.get(lookup), new_data={"action": action}
            )
        return response

    def _log_audit_event(self, request, action, resource_id, new_data=None):
        try:
            user = request.user if getattr(request.user, "is_authenticated", False) else None
            AuditLog.objects.create(
                user=user,
                action=action,
                resource_type=self.audit_resource_type or self.__class__.__name__,
                resource_id=str(resource_id or ""),
                new_data=new_data,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
            )
        except Exception:  # noqa: BLE001 — audit logging must never break a read
            logger.warning("%s audit failed", action, exc_info=True)
