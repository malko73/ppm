from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0010_revert_project_icon_selection'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='page',
            name='icon_image',
        ),
        migrations.RemoveField(
            model_name='page',
            name='show_icon',
        ),
    ]
