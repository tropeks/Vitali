# Sprint 12 WhatsApp Module — Code Review Findings

**Review date:** 2026-04-05  
**Module:** `backend/apps/whatsapp/`  
**Sprint:** S-032 / S-033 / S-034 / S-035  
**Status:** 5 critical bugs identified — all fixed in the same commit.

---

## Bug 1 — `_parse_date_selection` returns `int`, but `slots` keys are ISO date strings (CRITICAL — no bookings complete)

**File:** `backend/apps/whatsapp/fsm.py`  
**Method:** `_parse_date_selection` / `_state_SELECTING_DATE`

`_parse_date_selection` returns the raw integer parsed from the user's input (e.g. `1`).
In `_state_SELECTING_DATE` the code then checks `if date_str not in slots:` where `slots` is
a `dict` whose keys are ISO-8601 date strings (`"2024-01-15"`, etc.). The integer `1` will
never be found in that dict, so the validation always fails and every date selection falls
through to `_unrecognized`. No appointment booking can ever proceed past the date-selection step.

**Fix:** Map the integer position back to `sorted(slots.keys())[idx - 1]` inside
`_state_SELECTING_DATE` before the membership check. Update `_parse_date_selection` to
return `Optional[int]` (no longer annotated as returning a string).

---

## Bug 2 — `_get_specialties` uses Professional PK as specialty ID — validation always fails (CRITICAL)

**File:** `backend/apps/whatsapp/fsm.py`  
**Method:** `_get_specialties` / `_state_SELECTING_SPECIALTY`

`_get_specialties` builds a list where each entry's `"id"` is a Professional row's primary
key (e.g. `{"id": 7, "name": "Cardiologia"}`). The user menu shows `1. Cardiologia`,
`2. Dermatologia`, so the user types `"1"` or `"2"`. `_parse_menu_selection` returns the
integer `1`. The validation `if specialty_id not in [s["id"] for s in specialties]` checks
whether `1` is in a list of Professional PKs (e.g. `[7, 23, 41]`) — it never is. Every
specialty selection is rejected.

A secondary issue is that `_get_professionals(specialty_id)` looks up `Professional.objects.filter(pk=specialty_id)` to obtain the specialty name, which is fragile and DB-specific.

**Fix:** Change `_get_specialties` to return sequential menu IDs (`1, 2, 3, …`) and sort by name.  
Store the **specialty name** (not a PK) in context. Change `_get_professionals` to filter
directly by specialty name.

---

## Bug 3 — `select_for_update()` outside `transaction.atomic()` in tasks.py (CRITICAL — TransactionManagementError + race condition)

**File:** `backend/apps/whatsapp/tasks.py`  
**Tasks:** `send_appointment_reminders`, `send_satisfaction_surveys`

`select_for_update(skip_locked=True)` is called on querysets that are evaluated outside
any `transaction.atomic()` block. Django requires an active transaction for `select_for_update`.
In autocommit mode this raises `TransactionManagementError` at query evaluation time, crashing
both Celery tasks. Even if the error were silenced, the lock would be released immediately
(no-op), leaving the race condition fully intact and enabling double-sends.

**Fix:** Wrap the queryset evaluation and subsequent status-update saves in
`transaction.atomic()` in both tasks.

---

## Bug 4 — Webhook accepts all traffic when `WHATSAPP_WEBHOOK_SECRET` is empty (SECURITY — fail-open)

**File:** `backend/apps/whatsapp/gateway.py`  
**Function:** `verify_webhook_signature`

```python
if not secret:
    logger.warning("WHATSAPP_WEBHOOK_SECRET not set — skipping HMAC verification")
    return True   # ← fail-open
```

When the environment variable is missing or blank, the function returns `True`, allowing
any HTTP client to inject arbitrary payloads into the webhook endpoint without
authentication. This is an unauthenticated code-execution vector for the FSM.

**Fix:** Return `False` when the secret is not configured. The warning log is preserved so
operators notice the misconfiguration.

---

## Bug 5 — CPF mask regex exposes last digit (PRIVACY — LGPD violation)

**File:** `backend/apps/whatsapp/views.py`  
**Function:** `_log_message`

```python
preview = re.sub(
    r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}",
    lambda m: "***-***-**" + m.group()[-1],   # ← leaks last digit
    preview,
)
```

The replacement appends the last character of the CPF match, exposing one digit.
For example `123.456.789-09` becomes `"***-***-**9"`. Storing even one real digit of a
CPF in logs may constitute a LGPD violation under Brazil's data-minimisation principle.

**Fix:** Replace with the static string `"***.***.***-**"` (fully masked, no captured groups).

---

## Summary

| # | Severity | File | Impact |
|---|----------|------|--------|
| 1 | Critical | fsm.py | Zero bookings complete |
| 2 | Critical | fsm.py | Zero bookings complete |
| 3 | Critical | tasks.py | Tasks crash + reminder double-send |
| 4 | High     | gateway.py | Unauthenticated webhook injection |
| 5 | Medium   | views.py | LGPD violation — CPF digit in logs |

All five bugs were fixed in commit immediately following this review.
