from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0004_project_participants'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='is_finalized',
            field=models.BooleanField(default=False),
        ),
    ]
