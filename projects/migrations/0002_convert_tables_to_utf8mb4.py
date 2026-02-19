from django.db import migrations


def convert_projects_tables_to_utf8mb4(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE projects_project CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cursor.execute(
            "ALTER TABLE projects_page CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            convert_projects_tables_to_utf8mb4,
            migrations.RunPython.noop,
        ),
    ]
