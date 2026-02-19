import django.db.models.deletion
import projects.models
from django.db import migrations, models


def seed_project_templates(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    ProjectTemplate = apps.get_model('projects', 'ProjectTemplate')
    Page = apps.get_model('projects', 'Page')

    for project in Project.objects.all():
        if ProjectTemplate.objects.filter(project_id=project.id).exists():
            continue
        template_file = getattr(project, 'template_file', None)
        if not template_file:
            continue
        template = ProjectTemplate.objects.create(
            project_id=project.id,
            name='既存テンプレート',
            template_file=template_file,
            is_default=True,
        )
        Page.objects.filter(project_id=project.id, project_template__isnull=True).update(project_template_id=template.id)


def remove_seeded_project_templates(apps, schema_editor):
    ProjectTemplate = apps.get_model('projects', 'ProjectTemplate')
    Page = apps.get_model('projects', 'Page')
    Page.objects.update(project_template=None)
    ProjectTemplate.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0005_page_is_finalized'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='template_file',
            field=models.FileField(blank=True, null=True, upload_to='templates/', validators=[projects.models.validate_pdf]),
        ),
        migrations.CreateModel(
            name='ProjectTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('template_file', models.FileField(upload_to='templates/', validators=[projects.models.validate_pdf])),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='templates', to='projects.project')),
            ],
            options={
                'ordering': ['-is_default', 'id'],
            },
        ),
        migrations.AddField(
            model_name='page',
            name='project_template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pages', to='projects.projecttemplate'),
        ),
        migrations.RunPython(seed_project_templates, remove_seeded_project_templates),
    ]
