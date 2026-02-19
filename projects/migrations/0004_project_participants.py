from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_convert_mysql_collation_utf8mb4'),
        ('projects', '0003_pageimage'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='participants',
            field=models.ManyToManyField(blank=True, related_name='participating_projects', to=settings.AUTH_USER_MODEL),
        ),
    ]
