"""
Management command: create_default_roles
Usage: python manage.py create_default_roles [--schema <schema_name>]

Creates the six default system roles in the current (or specified) tenant schema.
Safe to run multiple times — uses get_or_create.
"""
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Create default system roles in the current tenant schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Tenant schema name. If omitted, uses the currently active schema.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            default=False,
            help="Overwrite permissions of existing roles.",
        )

    def handle(self, *args, **options):
        from apps.core.models import Role
        from apps.core.permissions import DEFAULT_ROLES

        schema = options["schema"]
        overwrite = options["overwrite"]

        def _create_roles():
            created_count = 0
            updated_count = 0
            for role_name, perms in DEFAULT_ROLES.items():
                role, created = Role.objects.get_or_create(
                    name=role_name,
                    defaults={"permissions": perms, "is_system": True},
                )
                if not created and overwrite:
                    role.permissions = perms
                    role.is_system = True
                    role.save(update_fields=["permissions", "is_system"])
                    updated_count += 1
                elif created:
                    created_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Roles: {created_count} criadas, {updated_count} atualizadas."
                )
            )

        if schema:
            self.stdout.write(f"Criando roles no schema: {schema}")
            with schema_context(schema):
                _create_roles()
        else:
            self.stdout.write("Criando roles no schema ativo...")
            _create_roles()
