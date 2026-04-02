"""
Idempotent management command to seed AIPromptTemplate records.
Uses get_or_create — safe to run multiple times. Bumping version creates a new row
without overwriting the existing one (allowing rollback by deactivating the new version).

Usage:
    python manage.py seed_prompt_templates
"""
from django.core.management.base import BaseCommand

from apps.ai.models import AIPromptTemplate

TEMPLATES = [
    {
        "name": "tuss_suggest",
        "version": 1,
        "system_prompt": (
            "You are a Brazilian healthcare billing assistant. "
            "Given a procedure description and guide type, return the most relevant TUSS codes "
            "from the provided candidates. Respond ONLY with a JSON array of objects with keys "
            "'tuss_code' and 'rank'. Do not include any other text."
        ),
        "user_prompt_template": (
            "Guide type: {guide_type}\n"
            "Procedure description: {description}\n\n"
            "Candidates (tuss_code: description):\n{candidates}\n\n"
            "Return up to 3 best matches as JSON array: "
            '[{{"tuss_code": "...", "rank": 1}}, ...]'
        ),
        "is_active": True,
    },
    {
        "name": "glosa_predict",
        "version": 1,
        "system_prompt": (
            "You are a Brazilian healthcare claims auditor specializing in TISS billing. "
            "Analyze the provided procedure, insurer, and diagnosis codes, then predict "
            "the glosa (claim denial) risk. "
            "Respond ONLY with a JSON object with keys: "
            "'risk_level' (one of: low, medium, high), "
            "'risk_reason' (plain Portuguese, max 200 chars), "
            "'risk_code' (TISS glosa reason code 2-5 chars, or empty string if none applies). "
            "Do not include any other text."
        ),
        "user_prompt_template": (
            "TUSS code: {tuss_code}\n"
            "Insurer: {insurer_name} (ANS: {insurer_ans_code})\n"
            "Guide type: {guide_type}\n"
            "CID-10 diagnoses: {cid10_codes}\n\n"
            "Predict glosa risk as JSON: "
            '{{"risk_level": "low|medium|high", "risk_reason": "...", "risk_code": "..."}}'
        ),
        "is_active": True,
    },
]


class Command(BaseCommand):
    help = "Seed AI prompt templates (idempotent — safe to re-run)."

    def handle(self, *args, **options):
        created_count = 0
        skipped_count = 0

        for tmpl in TEMPLATES:
            _, created = AIPromptTemplate.objects.get_or_create(
                name=tmpl["name"],
                version=tmpl["version"],
                defaults={
                    "system_prompt": tmpl["system_prompt"],
                    "user_prompt_template": tmpl["user_prompt_template"],
                    "is_active": tmpl["is_active"],
                },
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Created: {tmpl['name']} v{tmpl['version']}")
                )
            else:
                skipped_count += 1
                self.stdout.write(f"  Skipped (exists): {tmpl['name']} v{tmpl['version']}")

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_prompt_templates done: {created_count} created, {skipped_count} skipped."
            )
        )
