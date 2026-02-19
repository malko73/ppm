from django.db import migrations, models
import django.db.models.deletion
import projects.models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0002_convert_tables_to_utf8mb4'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64)),
                ('label', models.CharField(blank=True, max_length=100)),
                ('image', models.ImageField(upload_to='pages/', validators=[projects.models.validate_image_size])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='projects.page')),
            ],
            options={
                'ordering': ['id'],
                'unique_together': {('page', 'key')},
            },
        ),
    ]
