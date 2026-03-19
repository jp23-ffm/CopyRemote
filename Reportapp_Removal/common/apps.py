from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'common'

    def ready(self):
        import common.saml_patch  # noqa: F401
        import common.signals     # noqa: F401
