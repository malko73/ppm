from django.core.management.base import BaseCommand, CommandError

from accounts.models import AuthEventLog


class Command(BaseCommand):
    help = 'Detect tampering in auth event logs by verifying hash-chain consistency.'

    def handle(self, *args, **options):
        total = 0
        previous_hash = ''

        for log in AuthEventLog.objects.order_by('id').iterator():
            total += 1

            expected_payload_hash = log.compute_payload_hash()
            if log.payload_hash != expected_payload_hash:
                raise CommandError(
                    f'Payload hash mismatch at id={log.id}: stored={log.payload_hash} expected={expected_payload_hash}'
                )

            if log.previous_hash != previous_hash:
                raise CommandError(
                    f'Chain break at id={log.id}: stored previous_hash={log.previous_hash} expected={previous_hash}'
                )

            expected_entry_hash = log.compute_entry_hash()
            if log.entry_hash != expected_entry_hash:
                raise CommandError(
                    f'Entry hash mismatch at id={log.id}: stored={log.entry_hash} expected={expected_entry_hash}'
                )

            previous_hash = log.entry_hash

        self.stdout.write(self.style.SUCCESS(f'Auth log chain verified. total_records={total}'))
