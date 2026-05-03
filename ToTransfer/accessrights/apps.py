from django.apps import AppConfig


class AccessRightsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accessrights'
    verbose_name = 'Access Rights'

    def ready(self):
        import accessrights.signals  # noqa: F401
