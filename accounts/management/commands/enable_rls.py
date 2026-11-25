from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections

from accounts.rls import enable_row_level_security


class Command(BaseCommand):
    help = "Enable PostgreSQL Row Level Security on every project table (fixes ISS-01)."

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options):
        conn = connections[options["database"]]
        if conn.vendor != "postgresql":
            self.stdout.write("Not a PostgreSQL database; nothing to do.")
            return
        changed = enable_row_level_security(conn)
        if changed:
            self.stdout.write(self.style.SUCCESS(f"RLS enabled on {len(changed)} table(s):"))
            for table in changed:
                self.stdout.write(f"  {table}")
        else:
            self.stdout.write(self.style.SUCCESS("RLS is already enabled on every table."))
