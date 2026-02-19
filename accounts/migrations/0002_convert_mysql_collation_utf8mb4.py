from django.db import migrations


TARGET_CHARSET = "utf8mb4"
TARGET_COLLATION = "utf8mb4_unicode_ci"


def convert_mysql_tables_to_utf8mb4(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return

    db_name = schema_editor.connection.settings_dict["NAME"]

    with schema_editor.connection.cursor() as cursor:
        # Ensure new tables default to utf8mb4.
        cursor.execute(
            f"ALTER DATABASE `{db_name}` CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}"
        )

        # Convert all base tables that are still using a non-utf8mb4 collation.
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
              AND TABLE_TYPE = 'BASE TABLE'
              AND (TABLE_COLLATION IS NULL OR TABLE_COLLATION NOT LIKE 'utf8mb4%%')
            """,
            [db_name],
        )
        table_names = [row[0] for row in cursor.fetchall()]

        for table_name in table_names:
            cursor.execute(
                f"ALTER TABLE `{table_name}` CONVERT TO CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("projects", "0003_pageimage"),
    ]

    operations = [
        migrations.RunPython(
            convert_mysql_tables_to_utf8mb4,
            migrations.RunPython.noop,
        ),
    ]
