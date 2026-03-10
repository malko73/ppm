from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_convert_mysql_collation_utf8mb4'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthEventLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now, editable=False)),
                ('event', models.CharField(choices=[('login_success', 'Login Success'), ('login_failed', 'Login Failed'), ('logout', 'Logout')], db_index=True, max_length=32)),
                ('identifier', models.CharField(blank=True, default='', max_length=255)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('request_id', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('reason', models.CharField(choices=[('unknown', 'Unknown'), ('wrong_password', 'Wrong Password'), ('user_not_found', 'User Not Found'), ('inactive_user', 'Inactive User'), ('invalid_identifier', 'Invalid Identifier')], default='unknown', max_length=64)),
                ('previous_hash', models.CharField(blank=True, default='', max_length=64)),
                ('payload_hash', models.CharField(editable=False, max_length=64)),
                ('entry_hash', models.CharField(db_index=True, editable=False, max_length=64, unique=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auth_event_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Auth Event Log',
                'verbose_name_plural': 'Auth Event Logs',
                'ordering': ('id',),
            },
        ),
    ]
