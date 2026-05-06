from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0013_project_category'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='page',
            constraint=models.UniqueConstraint(
                fields=['project', 'page_number'],
                name='uq_page_project_page_number'
            ),
        ),
    ]
