from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0012_projecttemplate_default_positions'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='category',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
        ),
    ]
