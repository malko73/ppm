import projects.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0006_projecttemplate_page_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='icon_image',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='pages/',
                validators=[projects.models.validate_image_size],
            ),
        ),
        migrations.AddField(
            model_name='page',
            name='show_icon',
            field=models.BooleanField(default=True),
        ),
    ]
