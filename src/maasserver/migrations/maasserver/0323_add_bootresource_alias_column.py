# Generated by Django 3.2.12 on 2024-05-20 13:30

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("maasserver", "0322_current_script_set_foreign_keys_readd"),
    ]

    operations = [
        migrations.AddField(
            model_name="bootresource",
            name="alias",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterUniqueTogether(
            name="bootresource",
            unique_together={("name", "architecture", "alias")},
        ),
    ]
