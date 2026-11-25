from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        import accounts.signals  # noqa: F401

        from .rls import enable_rls_after_migrate

        # ISS-01: keep Row Level Security on for every table after each migrate.
        post_migrate.connect(
            enable_rls_after_migrate,
            sender=self,
            dispatch_uid="accounts.enable_rls_after_migrate",
        )
