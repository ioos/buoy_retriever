from django.apps import AppConfig


class NinjaPostgrestConfig(AppConfig):
    name = "ninja_postgrest"
    label = "ninja_postgrest"
    verbose_name = "Django-Ninja PostgREST"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Register the custom ``__like`` / ``__ilike`` lookups so the PostgREST
        # ``like`` / ``ilike`` operators map directly onto SQL ``LIKE`` / ``ILIKE``.
        from . import lookups  # noqa: F401  (import for side effect of registration)

        lookups.register_lookups()
