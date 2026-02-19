from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0009_page_project_icons_m2m'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='page',
            name='project_icons',
        ),
        migrations.RemoveField(
            model_name='page',
            name='project_icon',
        ),
        migrations.DeleteModel(
            name='ProjectIcon',
        ),
    ]
