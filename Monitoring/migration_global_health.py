# Migration Django pour GlobalHealthStatus
# Fichier: api/migrations/XXXX_add_global_health_status.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', 'XXXX_previous_migration'),  # Remplacer par ta dernière migration
    ]

    operations = [
        migrations.CreateModel(
            name='GlobalHealthStatus',
            fields=[
                ('id', models.IntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(
                    choices=[('OK', 'OK'), ('Warning', 'Warning'), ('Error', 'Error'), ('Unknown', 'Unknown')],
                    default='Unknown',
                    help_text='État global des checks partagés',
                    max_length=20
                )),
                ('checks_data', models.JSONField(default=dict, help_text='Détails de tous les checks globaux')),
                ('last_updated', models.DateTimeField(auto_now=True, db_index=True, help_text='Dernière mise à jour des checks globaux')),
            ],
            options={
                'verbose_name': 'Global Health Status',
                'verbose_name_plural': 'Global Health Status',
                'db_table': 'global_health_status',
            },
        ),
    ]
