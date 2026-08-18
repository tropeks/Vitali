"""
Billing permissions — faturista or admin required for all billing views.
"""

from rest_framework.permissions import BasePermission


class IsFaturistaOrAdmin(BasePermission):
    """Allow access only to users with the 'faturista' or 'admin' role."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.has_role_permission("billing.read") or user.has_role_permission("billing.write")


class CanRecordInpatientFee(BasePermission):
    """Quem lança taxa/gás medicinal numa internação.

    Onda 2 / 2.1: o gate padrão de billing (``IsFaturistaOrAdmin``) não serve
    aqui. Quem registra oxigênio, incubadora ou bomba de infusão está à beira do
    leito — é enfermagem, não faturamento. Exigir permissão de billing deixaria a
    receita tão trancada quanto estava antes de existir o endpoint, só que por
    autorização em vez de por ausência de rota.

    Aceita ``billing.write`` (faturamento corrigindo/complementando a conta) OU
    ``emr.write`` (equipe clínica lançando no momento do cuidado). Decisão do
    Capitão em 2026-08-18.

    Note que a leitura NÃO basta: ``billing.read`` autoriza consultar a conta,
    não escrever nela. Este gate cobre create, list e retrieve do mesmo viewset;
    quem pode lançar pode ver o que lançou.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.has_role_permission("billing.write") or user.has_role_permission("emr.write")
