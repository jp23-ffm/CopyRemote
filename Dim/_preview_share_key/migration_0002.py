from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0001_initial'),
    ]

    operations = [
        # ShareAnnotation: rename SHARE_ID → SHARE_NAME
        migrations.RenameField(
            model_name='shareannotation',
            old_name='SHARE_ID',
            new_name='SHARE_NAME',
        ),

        # StorageShare: drop index on ID
        migrations.RemoveIndex(
            model_name='storageshare',
            name='storage_sto_ID_<hash>_idx',  # à ajuster avec le vrai nom généré
        ),
        migrations.AlterField(
            model_name='storageshare',
            name='ID',
            field=models.CharField(db_column='share_id', max_length=255),
        ),

        # StorageShare: add index on SHARE_NAME
        migrations.AlterField(
            model_name='storageshare',
            name='SHARE_NAME',
            field=models.CharField(blank=True, db_index=True, max_length=500, null=True),
        ),
        migrations.AddIndex(
            model_name='storageshare',
            index=models.Index(fields=['SHARE_NAME'], name='storage_sto_SHARE_N_<hash>_idx'),
        ),
    ]
