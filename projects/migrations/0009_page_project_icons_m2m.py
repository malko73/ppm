from django.db import migrations, models


def copy_single_icon_to_multiple(apps, schema_editor):
    Page = apps.get_model('projects', 'Page')
    for page in Page.objects.exclude(project_icon__isnull=True):
        page.project_icons.add(page.project_icon_id)


def reverse_copy_single_icon_to_multiple(apps, schema_editor):
    Page = apps.get_model('projects', 'Page')
    for page in Page.objects.all():
        first_icon = page.project_icons.order_by('id').first()
        page.project_icon_id = first_icon.id if first_icon else None
        page.save(update_fields=['project_icon'])


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_projecticon_page_project_icon'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='project_icons',
            field=models.ManyToManyField(blank=True, related_name='pages_using_icons', to='projects.projecticon'),
        ),
        migrations.RunPython(copy_single_icon_to_multiple, reverse_copy_single_icon_to_multiple),
    ]
