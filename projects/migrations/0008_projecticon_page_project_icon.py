import django.db.models.deletion
import projects.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_page_icon_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectIcon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=100)),
                ('image', models.ImageField(upload_to='project_icons/', validators=[projects.models.validate_image_size])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'project',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='icons',
                        to='projects.project',
                    ),
                ),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddField(
            model_name='page',
            name='project_icon',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pages_using_icon',
                to='projects.projecticon',
            ),
        ),
    ]
