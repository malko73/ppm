import copy

from django.db import migrations, models


def populate_template_positions(apps, schema_editor):
    ProjectTemplate = apps.get_model('projects', 'ProjectTemplate')
    for template in ProjectTemplate.objects.select_related('project').all():
        if template.default_positions:
            continue
        project_positions = getattr(template.project, 'default_positions', None) or {}
        if project_positions:
            template.default_positions = copy.deepcopy(project_positions)
            template.save(update_fields=['default_positions'])


def clear_template_positions(apps, schema_editor):
    ProjectTemplate = apps.get_model('projects', 'ProjectTemplate')
    ProjectTemplate.objects.all().update(default_positions={})


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0011_remove_page_icon_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='projecttemplate',
            name='default_positions',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(populate_template_positions, clear_template_positions),
    ]
