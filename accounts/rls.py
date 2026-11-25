"""Turn on PostgreSQL Row Level Security (RLS) for the project's tables.

Fixes PD2 issue ISS-01: tables created by ``migrate`` on Supabase had RLS
switched off, so Supabase showed them as UNRESTRICTED and they could be read
through Supabase's public REST API with the anon key.

Django connects as the table owner, and a table owner is not subject to RLS
unless FORCE ROW LEVEL SECURITY is used, so the app keeps working. Supabase's
``anon`` and ``authenticated`` API roles get no policies, so they are denied.
"""

from django.db import connection

# Only the project's own schema is touched. Table names come from Django's
# introspection (never from user input) and are quoted by the backend.
SCHEMA = "public"


def tables_without_rls(cursor):
    cursor.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND NOT c.relrowsecurity
        ORDER BY c.relname
        """,
        [SCHEMA],
    )
    return [row[0] for row in cursor.fetchall()]


def enable_row_level_security(using_connection=None):
    """Enable RLS on every table in the public schema that does not have it.

    Returns the list of tables that were changed. Does nothing on databases
    other than PostgreSQL (for example SQLite).
    """
    conn = using_connection or connection
    if conn.vendor != "postgresql":
        return []
    changed = []
    with conn.cursor() as cursor:
        django_tables = set(conn.introspection.table_names(cursor))
        for table in tables_without_rls(cursor):
            if table not in django_tables:
                continue
            quoted = conn.ops.quote_name(table)
            cursor.execute(f"ALTER TABLE {SCHEMA}.{quoted} ENABLE ROW LEVEL SECURITY")
            changed.append(table)
    return changed


def enable_rls_after_migrate(sender, using="default", **kwargs):
    """post_migrate handler: runs after every ``migrate`` so new tables are covered."""
    from django.db import connections

    enable_row_level_security(connections[using])
