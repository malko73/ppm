from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import projects.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('template_file', models.FileField(upload_to='templates/', validators=[projects.models.validate_pdf])),
                ('default_positions', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at']},
        ),
        migrations.CreateModel(
            name='Page',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField(default=1)),
                ('page_number', models.PositiveIntegerField(default=1)),
                ('page_name', models.CharField(blank=True, max_length=255)),
                ('input_data', models.JSONField(blank=True, default=dict)),
                ('main_image', models.ImageField(blank=True, null=True, upload_to='pages/', validators=[projects.models.validate_image_size])),
                ('sub_image1', models.ImageField(blank=True, null=True, upload_to='pages/', validators=[projects.models.validate_image_size])),
                ('sub_image2', models.ImageField(blank=True, null=True, upload_to='pages/', validators=[projects.models.validate_image_size])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pages', to='projects.project')),
            ],
            options={'ordering': ['order', 'id']},
        ),
    ]
