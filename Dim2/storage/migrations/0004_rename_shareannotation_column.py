from django.db import migrations


class Migration(migrations.Migration):
    """Align DB with migration state: SHARE_NAME → share_key (0002 was applied before the rename target changed)."""

    dependencies = [
        ('storage', '0003_alter_objectannotation_name'),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE storage_shareannotation RENAME COLUMN "SHARE_NAME" TO share_key',
            reverse_sql='ALTER TABLE storage_shareannotation RENAME COLUMN share_key TO "SHARE_NAME"',
        ),
    ]
