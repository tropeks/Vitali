"""
ConversationFSM — WhatsApp appointment scheduling state machine.

Entry point: ConversationFSM(session, gateway).process(inbound_message)
Returns: list[str]  — outbound messages to send (in order)

Rules:
- select_for_update() on ConversationSession at start of process() prevents
  concurrent double-tap corruption.
- Slot reservation at CONFIRMING is atomic (transaction.atomic + select_for_update
  on overlapping Appointments).
- Keyword intent detection runs before menu matching: normalized PT-BR phrases
  are mapped to intents so "quero marcar" works the same as the menu button.
- Max 3 unrecognized inputs before FALLBACK_HUMAN transition.
- "sair" / "parar" from any state → OPTED_OUT immediately.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from .context import get_context, set_context
from .gateway import WhatsAppGateway, OptOutError

logger = logging.getLogger(__name__)

# ─── Intent detection ─────────────────────────────────────────────────────────

INTENT_MAP: dict[str, str] = {
    # Scheduling
    "agendar": "agendar",
    "quero agendar": "agendar",
    "marcar": "agendar",
    "quero marcar": "agendar",
    "quero consulta": "agendar",
    "consulta": "agendar",
    "nova consulta": "agendar",
    # Cancel
    "cancelar": "cancelar",
    "quero cancelar": "cancelar",
    "cancela": "cancelar",
    # Reschedule
    "remarcar": "remarcar",
    "quero remarcar": "remarcar",
    "reagendar": "remarcar",
    # Confirm
    "confirmar": "confirmar",
    "confirmado": "confirmar",
    "sim": "confirmar",
    "s": "confirmar",
    "ok": "confirmar",
    # Opt-in
    "aceitar": "optin",
    "aceito": "optin",
    "autorizo": "optin",
    "concordo": "optin",
    "1": "optin",
    # Opt-out
    "sair": "optout",
    "parar": "optout",
    "stop": "optout",
    "nao": "optout",
    "nao quero": "optout",
    "recusar": "optout",
    "2": "optout",
    # Help
    "ajuda": "ajuda",
    "menu": "ajuda",
    "opcoes": "ajuda",
    # Self/Other
    "para mim": "self",
    "eu": "self",
    "para outra pessoa": "other",
    "outra pessoa": "other",
    "para outra": "other",
}


def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    text = text.strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text


def detect_intent(text: str) -> Optional[str]:
    normalized = _normalize(text)
    return INTENT_MAP.get(normalized)


# ─── Message templates ─────────────────────────────────────────────────────────

LGPD_CONSENT_MSG = (
    "Olá! 👋 Sou o assistente virtual da clínica.\n\n"
    "Para enviar mensagens sobre consultas e lembretes, precisamos do seu consentimento "
    "conforme a LGPD (Lei 13.709/2018).\n\n"
    "✅ *Aceitar* — para receber informações sobre consultas\n"
    "❌ *Recusar* — para não receber mensagens\n\n"
    "Você pode cancelar a qualquer momento enviando *SAIR*."
)

OPTED_OUT_MSG = "✅ Você foi removido da nossa lista. Não enviaremos mais mensagens. Para voltar, envie qualquer mensagem."
OPTED_IN_MSG = "✅ Consentimento registrado! Agora posso te ajudar a agendar consultas."
FALLBACK_MSG_TEMPLATE = "Não entendi. Entre em contato com nossa equipe pelo telefone: {phone}"
UNRECOGNIZED_MSG = "Não entendi. Digite *menu* para ver as opções."
EXPIRED_MSG = "Sua sessão expirou. Digite *menu* para começar."
SELF_OR_OTHER_MSG = "A consulta é para você ou para outra pessoa?\n\n1️⃣ Para mim\n2️⃣ Para outra pessoa"
ASK_NAME_MSG = "Qual o nome completo da pessoa?"
ASK_CPF_MSG = "Qual o CPF da pessoa? (somente números)"
INVALID_CPF_MSG = "CPF inválido. Por favor, informe apenas os 11 dígitos numéricos do CPF."
SLOT_TAKEN_MSG = "Desculpe, esse horário acabou de ser reservado. Escolha outro:"
BOOKING_CANCELLED_MSG = "Agendamento cancelado. Se mudar de ideia, é só chamar! 😊"

CONFIRM_MSG_TEMPLATE = (
    "Confirmação do agendamento:\n\n"
    "🏥 Especialidade: {specialty}\n"
    "👨‍⚕️ Profissional: {professional}\n"
    "📅 Data: {date}\n"
    "⏰ Horário: {time}\n\n"
    "Confirmar este agendamento?"
)
CONFIRMED_MSG_TEMPLATE = (
    "✅ Consulta agendada com sucesso!\n\n"
    "📅 {date} às {time} com {professional}.\n\n"
    "Você receberá um lembrete 24h antes. Para cancelar, envie *cancelar*."
)


# ─── FSM ──────────────────────────────────────────────────────────────────────

class ConversationFSM:
    def __init__(self, session, gateway: WhatsAppGateway):
        self._session = session
        self._gateway = gateway
        self._clinic_phone = self._get_clinic_phone()

    def _get_clinic_phone(self) -> str:
        from django.conf import settings
        return getattr(settings, "WHATSAPP_CLINIC_PHONE", "+551199999999")

    def process(self, message: str, message_type: str = "text") -> list[str]:
        """
        Process an inbound message. Returns list of outbound message strings.
        Caller is responsible for actually sending them via gateway.
        session must already be locked via select_for_update() before calling.
        """
        session = self._session

        # Expire check
        if session.is_expired() and session.state not in ("IDLE", "OPTED_OUT"):
            session.state = "IDLE"
            set_context(session, mismatches=0)
            session.refresh_expiry()
            session.save()
            return [EXPIRED_MSG]

        # Global opt-out from any state
        intent = detect_intent(message)
        if intent == "optout":
            return self._do_optout()

        handler = getattr(self, f"_state_{session.state}", self._state_unknown)
        outbound = handler(message, message_type, intent)

        session.refresh_expiry()
        session.save()
        return outbound

    # ─── State handlers ───────────────────────────────────────────────────────

    def _state_IDLE(self, message, message_type, intent) -> list[str]:
        session = self._session
        contact = session.contact

        if not contact.opt_in:
            session.state = "PENDING_OPTIN"
            session.save()
            return [LGPD_CONSENT_MSG]

        session.state = "SELECTING_SELF_OR_OTHER"
        session.save()
        return [OPTED_IN_MSG + "\n\n" + SELF_OR_OTHER_MSG]

    def _state_PENDING_OPTIN(self, message, message_type, intent) -> list[str]:
        session = self._session
        contact = session.contact

        if intent == "optin":
            contact.do_opt_in()
            session.state = "SELECTING_SELF_OR_OTHER"
            session.save()
            return [OPTED_IN_MSG + "\n\n" + SELF_OR_OTHER_MSG]
        elif intent == "optout":
            contact.do_opt_out()
            session.state = "OPTED_OUT"
            session.save()
            return [OPTED_OUT_MSG]
        else:
            return self._unrecognized([LGPD_CONSENT_MSG])

    def _state_SELECTING_SELF_OR_OTHER(self, message, message_type, intent) -> list[str]:
        session = self._session

        if intent == "self" or message.strip() == "1":
            set_context(session, booking_for_self=True)
            session.state = "SELECTING_SPECIALTY"
            session.save()
            return self._send_specialty_menu()

        elif intent == "other" or message.strip() == "2":
            set_context(session, booking_for_self=False)
            session.state = "CAPTURING_NAME"
            session.save()
            return [ASK_NAME_MSG]

        else:
            return self._unrecognized([SELF_OR_OTHER_MSG])

    def _state_CAPTURING_NAME(self, message, message_type, intent) -> list[str]:
        session = self._session
        name = message.strip()
        if len(name) < 3:
            return self._unrecognized([ASK_NAME_MSG])
        set_context(session, other_name=name)
        session.state = "CAPTURING_CPF"
        session.save()
        return [ASK_CPF_MSG]

    def _state_CAPTURING_CPF(self, message, message_type, intent) -> list[str]:
        session = self._session
        cpf_raw = re.sub(r"\D", "", message.strip())
        if not _is_valid_cpf(cpf_raw):
            ctx = get_context(session)
            mismatches = (ctx.get("mismatches") or 0) + 1
            if mismatches >= 3:
                session.state = "FALLBACK_HUMAN"
                session.save()
                return [FALLBACK_MSG_TEMPLATE.format(phone=self._clinic_phone)]
            set_context(session, mismatches=mismatches)
            session.save()
            return [INVALID_CPF_MSG]

        # Match or create patient
        patient = self._match_or_create_patient(session, cpf_raw)
        # Replace CPF in context immediately with patient PK (LGPD)
        set_context(session, other_cpf=None, other_patient_id=str(patient.pk), mismatches=0)
        session.state = "SELECTING_SPECIALTY"
        session.save()
        return self._send_specialty_menu()

    def _state_SELECTING_SPECIALTY(self, message, message_type, intent) -> list[str]:
        session = self._session
        idx = self._parse_menu_selection(message)
        if idx is None:
            return self._unrecognized(self._send_specialty_menu())

        specialties = self._get_specialties()
        if idx < 1 or idx > len(specialties):
            return self._unrecognized(self._send_specialty_menu())

        # Store the specialty name (natural key) rather than a PK
        specialty_name = specialties[idx - 1]["name"]
        set_context(session, specialty_id=specialty_name, mismatches=0)
        session.state = "SELECTING_PROFESSIONAL"
        session.save()
        return self._send_professional_menu(specialty_name)

    def _state_SELECTING_PROFESSIONAL(self, message, message_type, intent) -> list[str]:
        session = self._session
        ctx = get_context(session)
        professional_id = self._parse_menu_selection(message)

        professionals = self._get_professionals(ctx.get("specialty_id"))
        if professional_id not in [p["id"] for p in professionals]:
            return self._unrecognized(self._send_professional_menu(ctx.get("specialty_id")))

        set_context(session, professional_id=professional_id, mismatches=0)
        session.state = "SELECTING_DATE"
        session.save()
        return self._send_date_menu(professional_id)

    def _state_SELECTING_DATE(self, message, message_type, intent) -> list[str]:
        session = self._session
        ctx = get_context(session)

        slots = self._get_slots(ctx.get("professional_id"))
        sorted_dates = sorted(slots.keys())
        idx = self._parse_date_selection(message)
        if idx is None or idx < 1 or idx > len(sorted_dates):
            return self._unrecognized(self._send_date_menu(ctx.get("professional_id")))

        date_str = sorted_dates[idx - 1]
        set_context(session, date=date_str, mismatches=0)
        session.state = "SELECTING_TIME"
        session.save()
        return self._send_time_menu(slots[date_str])

    def _state_SELECTING_TIME(self, message, message_type, intent) -> list[str]:
        session = self._session
        ctx = get_context(session)
        slot_idx = self._parse_menu_selection(message)

        slots = self._get_slots(ctx.get("professional_id"))
        date_str = ctx.get("date")
        if not date_str or date_str not in slots:
            return self._unrecognized(["Ocorreu um erro. Digite *menu* para recomeçar."])

        day_slots = slots[date_str]
        if slot_idx is None or slot_idx < 1 or slot_idx > len(day_slots):
            return self._unrecognized(self._send_time_menu(day_slots))

        chosen = day_slots[slot_idx - 1]
        set_context(session, slot_start=chosen.start_iso, slot_end=chosen.end_iso, mismatches=0)
        session.state = "CONFIRMING"
        session.save()
        return self._send_confirm_summary()

    def _state_CONFIRMING(self, message, message_type, intent) -> list[str]:
        session = self._session

        if intent == "confirmar":
            return self._do_confirm_booking()
        elif intent == "cancelar":
            session.state = "IDLE"
            set_context(session, mismatches=0)
            session.save()
            return [BOOKING_CANCELLED_MSG]
        elif intent == "remarcar":
            ctx = get_context(session)
            session.state = "SELECTING_DATE"
            set_context(session, date=None, slot_start=None, slot_end=None, mismatches=0)
            session.save()
            return self._send_date_menu(ctx.get("professional_id"))
        else:
            return self._unrecognized(self._send_confirm_summary())

    def _state_CONFIRMED(self, message, message_type, intent) -> list[str]:
        session = self._session
        # New message after confirmed — restart scheduling
        session.state = "SELECTING_SELF_OR_OTHER"
        set_context(session, specialty_id=None, professional_id=None, date=None,
                    slot_start=None, slot_end=None, mismatches=0)
        session.save()
        return [SELF_OR_OTHER_MSG]

    def _state_FALLBACK_HUMAN(self, message, message_type, intent) -> list[str]:
        return [FALLBACK_MSG_TEMPLATE.format(phone=self._clinic_phone)]

    def _state_OPTED_OUT(self, message, message_type, intent) -> list[str]:
        # Patient messaged again after opting out — re-send opt-in prompt
        session = self._session
        contact = session.contact
        session.state = "PENDING_OPTIN"
        session.save()
        return [LGPD_CONSENT_MSG]

    def _state_unknown(self, message, message_type, intent) -> list[str]:
        return [UNRECOGNIZED_MSG]

    # ─── Opt-out ──────────────────────────────────────────────────────────────

    def _do_optout(self) -> list[str]:
        session = self._session
        contact = session.contact
        contact.do_opt_out()
        session.state = "OPTED_OUT"
        set_context(session, mismatches=0)
        session.save()
        return [OPTED_OUT_MSG]

    # ─── Booking confirmation (atomic slot reservation) ───────────────────────

    def _do_confirm_booking(self) -> list[str]:
        from apps.emr.models import Appointment, Professional
        session = self._session
        ctx = get_context(session)
        contact = session.contact

        try:
            professional = Professional.objects.get(pk=ctx["professional_id"])
        except (Professional.DoesNotExist, KeyError):
            return ["Ocorreu um erro ao confirmar. Por favor, tente novamente."]

        # Determine patient
        if ctx.get("booking_for_self"):
            patient = contact.patient
        else:
            from apps.emr.models import Patient
            try:
                patient = Patient.objects.get(pk=ctx.get("other_patient_id"))
            except Patient.DoesNotExist:
                return ["Não encontramos o paciente. Por favor, tente novamente."]

        if patient is None:
            return ["Não encontramos seu cadastro. Por favor, entre em contato com a clínica."]

        from datetime import datetime as dt
        try:
            start = dt.fromisoformat(ctx["slot_start"])
            end = dt.fromisoformat(ctx["slot_end"])
        except (KeyError, ValueError):
            return ["Horário inválido. Por favor, escolha outro horário."]

        # Atomic slot reservation — re-check availability inside transaction
        with transaction.atomic():
            overlapping = Appointment.objects.select_for_update().filter(
                professional=professional,
                status__in=["scheduled", "confirmed", "waiting", "in_progress"],
                start_time__lt=end,
                end_time__gt=start,
            )
            if overlapping.exists():
                # Slot was taken by someone else in the race window
                session.state = "SELECTING_TIME"
                set_context(session, slot_start=None, slot_end=None, mismatches=0)
                session.refresh_expiry()
                session.save()
                day_slots = self._get_slots(ctx.get("professional_id")).get(ctx.get("date"), [])
                return [SLOT_TAKEN_MSG] + self._send_time_menu(day_slots)

            appointment = Appointment.objects.create(
                patient=patient,
                professional=professional,
                start_time=start,
                end_time=end,
                status="scheduled",
                source="whatsapp",
            )

        # Link appointment to message logs
        MessageLog = None
        try:
            from .models import MessageLog
            MessageLog.objects.filter(
                contact=contact, appointment__isnull=True
            ).update(appointment=appointment)
        except Exception:
            pass

        # Delete session (CPF/PII gone)
        session.delete()

        return [CONFIRMED_MSG_TEMPLATE.format(
            date=start.strftime("%d/%m/%Y"),
            time=start.strftime("%H:%M"),
            professional=professional.user.full_name if hasattr(professional, "user") else str(professional),
        )]

    # ─── Menu builders ────────────────────────────────────────────────────────

    def _send_specialty_menu(self) -> list[str]:
        specialties = self._get_specialties()
        if not specialties:
            return ["Não há especialidades disponíveis no momento. Por favor, entre em contato com a clínica."]
        lines = ["Qual especialidade você procura?\n"]
        for i, s in enumerate(specialties, 1):
            lines.append(f"{i}. {s['name']}")
        return ["\n".join(lines)]

    def _send_professional_menu(self, specialty_id) -> list[str]:
        professionals = self._get_professionals(specialty_id)
        if not professionals:
            return ["Não há profissionais disponíveis para essa especialidade. Por favor, entre em contato com a clínica."]
        lines = ["Escolha o profissional:\n"]
        for i, p in enumerate(professionals, 1):
            lines.append(f"{i}. {p['name']}")
        return ["\n".join(lines)]

    def _send_date_menu(self, professional_id) -> list[str]:
        slots = self._get_slots(professional_id)
        if not slots:
            return ["Não há horários disponíveis nos próximos 7 dias. Por favor, entre em contato com a clínica."]
        lines = ["Escolha a data:\n"]
        for i, date_str in enumerate(sorted(slots.keys()), 1):
            d = date.fromisoformat(date_str)
            lines.append(f"{i}. {d.strftime('%d/%m/%Y (%A)')}")
        return ["\n".join(lines)]

    def _send_time_menu(self, day_slots) -> list[str]:
        if not day_slots:
            return ["Não há horários disponíveis nessa data. Escolha outra data."]
        lines = ["Escolha o horário:\n"]
        for i, slot in enumerate(day_slots, 1):
            lines.append(f"{i}. {slot.label}")
        return ["\n".join(lines)]

    def _send_confirm_summary(self) -> list[str]:
        from apps.emr.models import Professional
        from apps.emr.models import Appointment
        ctx = get_context(self._session)
        try:
            pro = Professional.objects.select_related("user").get(pk=ctx["professional_id"])
            pro_name = pro.user.full_name
            specialty = pro.specialty or "Consulta"
        except Exception:
            pro_name = "Profissional"
            specialty = "Consulta"

        try:
            from datetime import datetime as dt
            start = dt.fromisoformat(ctx["slot_start"])
            date_label = start.strftime("%d/%m/%Y")
            time_label = start.strftime("%H:%M")
        except Exception:
            date_label = ctx.get("date", "")
            time_label = ""

        msg = CONFIRM_MSG_TEMPLATE.format(
            specialty=specialty,
            professional=pro_name,
            date=date_label,
            time=time_label,
        )
        return [msg + "\n\nResponda: *confirmar*, *remarcar* ou *cancelar*"]

    # ─── Data helpers ─────────────────────────────────────────────────────────

    def _get_specialties(self) -> list[dict]:
        from apps.emr.models import Professional
        names = (
            Professional.objects.filter(is_active=True)
            .exclude(specialty="")
            .values_list("specialty", flat=True)
            .distinct()
            .order_by("specialty")
        )
        # Sequential IDs (1, 2, 3, …) match what _parse_menu_selection returns
        return [{"id": i + 1, "name": name} for i, name in enumerate(names)]

    def _get_professionals(self, specialty_id) -> list[dict]:
        from apps.emr.models import Professional
        qs = Professional.objects.filter(is_active=True).select_related("user")
        if specialty_id:
            # specialty_id is the specialty name string stored in context
            qs = qs.filter(specialty=specialty_id)
        return [{"id": p.pk, "name": p.user.full_name if hasattr(p, "user") else str(p)} for p in qs]

    def _get_slots(self, professional_id) -> dict:
        from apps.emr.models import Professional
        from .slot_service import get_available_slots
        if not professional_id:
            return {}
        try:
            pro = Professional.objects.get(pk=professional_id)
        except Professional.DoesNotExist:
            return {}
        return get_available_slots(pro)

    def _parse_menu_selection(self, message: str) -> Optional[int]:
        try:
            return int(message.strip())
        except ValueError:
            return None

    def _parse_date_selection(self, message: str) -> Optional[int]:
        """Parse number (menu position) for date selection. Caller maps to ISO date string."""
        try:
            return int(message.strip())
        except ValueError:
            return None

    def _match_or_create_patient(self, session, cpf_raw: str):
        """Find patient by CPF or create a new one with name from context."""
        from apps.emr.models import Patient
        from encrypted_model_fields.fields import EncryptedCharField
        ctx = get_context(session)
        name = ctx.get("other_name") or "Paciente WhatsApp"

        # Try to match by phone first (WhatsApp contact already linked)
        if session.contact.patient_id:
            return session.contact.patient

        # Search by CPF (encrypted — must iterate; index not possible on encrypted field)
        for patient in Patient.objects.filter(is_active=True):
            if re.sub(r"\D", "", patient.cpf or "") == cpf_raw:
                session.contact.patient = patient
                session.contact.save(update_fields=["patient"])
                return patient

        # Create new patient
        patient = Patient.objects.create(
            full_name=name,
            cpf=cpf_raw,
            birth_date="1900-01-01",  # placeholder — receptionist corrects later
            gender="N",
            whatsapp=session.contact.phone,
        )
        session.contact.patient = patient
        session.contact.save(update_fields=["patient"])
        return patient

    def _unrecognized(self, retry_messages: list[str]) -> list[str]:
        session = self._session
        ctx = get_context(session)
        mismatches = (ctx.get("mismatches") or 0) + 1
        set_context(session, mismatches=mismatches)
        if mismatches >= 3:
            session.state = "FALLBACK_HUMAN"
            session.save()
            return [FALLBACK_MSG_TEMPLATE.format(phone=self._clinic_phone)]
        session.save()
        return [UNRECOGNIZED_MSG] + retry_messages


# ─── CPF validation ───────────────────────────────────────────────────────────

def _is_valid_cpf(cpf: str) -> bool:
    """Basic Brazilian CPF checksum validation."""
    cpf = re.sub(r"\D", "", cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in range(9, 11):
        total = sum(int(cpf[j]) * (i + 1 - j) for j in range(i))
        digit = (total * 10 % 11) % 10
        if digit != int(cpf[i]):
            return False
    return True
