"""Build the read-only query that captures an exact undo for Phase 3.2D.

    uv run python -m scripts.build_32d_undo_snapshot > snapshot.sql

The table list and function signatures are read from the 3.2D migration
itself, so the undo covers exactly what 3.2D changes. The query returns the
undo script as one text value; save it in rollback/. It was run through a
full apply-and-undo round trip on a replica by
scripts/replica_undo_32d_test.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sql = (ROOT / "sql" / "phase-3.2d-security-hardening.sql").read_text(encoding="utf-8")
sql = sql.replace("\r\n", "\n")
body = sql[sql.index("$phase32d_preflight$;") : sql.index("DO $phase32d_postflight$")]
tables = sorted(set(re.findall(r"ON TABLE public\.([a-z_]+)", body)))
signatures = re.findall(
    r"^ALTER FUNCTION (public\.[a-z_]+\([^)]*\))\s*\nOWNER TO postgres;",
    sql,
    flags=re.M,
)
assert len(tables) == 13, tables
assert len(signatures) == 6, signatures

table_values = ", ".join(f"('{t}')" for t in tables)
table_array = ", ".join(f"'{t}'" for t in tables)
# The same list inside the quoted DO block the snapshot emits.
table_array_quoted = ", ".join(f"''{t}''" for t in tables)
drops = "\\n".join(f"DROP FUNCTION IF EXISTS {s};" for s in signatures)

QUERY = f"""-- READ ONLY. Run BEFORE the Phase 3.2D migration.
-- Returns, as one text value, a script that puts back exactly what 3.2D will
-- change: every policy and every PUBLIC/anon/authenticated/service_role grant
-- on its 13 tables, and removes its 6 functions. Nothing is changed by this.
with
tables(tbl) as (values {table_values}),
grantees(oid, label) as (
    select 0::oid, 'PUBLIC'::text
    union all
    select r.oid, quote_ident(r.rolname::text)
    from pg_catalog.pg_roles as r
    where r.rolname in ('anon', 'authenticated', 'service_role')
),
parts(ord, body) as (
    select 0, '-- Phase 3.2D UNDO, generated ' || now()::text
        || E' from the live state before the migration.\\n'
        || E'-- Run only if 3.2D was applied and must be reversed.\\n'
        || E'BEGIN;\\nSET LOCAL lock_timeout = ''5s'';'

    union all
    select 1, case
        when (select count(*) from pg_catalog.pg_policies
              where schemaname = 'public' and policyname like 'phase32d\\_%') = 0
        then '-- snapshot check: 3.2D not applied'
        else 'DO $invalid$ BEGIN RAISE EXCEPTION ''3.2D undo snapshot is invalid; '
             || 'do not use this script''; END $invalid$;'
    end

    union all
    select 10, 'DO $drop_policies$
DECLARE target record;
BEGIN
    FOR target IN
        SELECT policyname, tablename FROM pg_catalog.pg_policies
        WHERE schemaname = ''public''
          AND tablename = ANY (ARRAY[{table_array_quoted}])
    LOOP
        EXECUTE pg_catalog.format(
            ''DROP POLICY %I ON public.%I'', target.policyname, target.tablename
        );
    END LOOP;
END
$drop_policies$;'

    union all
    select 20, E'{drops}'

    union all
    select 30 + row_number() over (order by t.tbl),
        format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated, service_role;', t.tbl)
        || coalesce(E'\\n' || (
            select string_agg(
                format('GRANT %s ON TABLE public.%I TO %s%s;',
                       a.privilege_type, t.tbl, g.label,
                       case when a.is_grantable then ' WITH GRANT OPTION' else '' end),
                E'\\n' order by g.label, a.privilege_type)
            from pg_catalog.pg_class as c
            cross join lateral pg_catalog.aclexplode(c.relacl) as a
            join grantees as g on g.oid = a.grantee
            where c.oid = format('public.%I', t.tbl)::pg_catalog.regclass
        ), '')
        || coalesce(E'\\n' || (
            select string_agg(
                format('GRANT %s (%I) ON TABLE public.%I TO %s%s;',
                       a.privilege_type, att.attname, t.tbl, g.label,
                       case when a.is_grantable then ' WITH GRANT OPTION' else '' end),
                E'\\n' order by att.attnum, g.label, a.privilege_type)
            from pg_catalog.pg_attribute as att
            cross join lateral pg_catalog.aclexplode(att.attacl) as a
            join grantees as g on g.oid = a.grantee
            where att.attrelid = format('public.%I', t.tbl)::pg_catalog.regclass
              and att.attnum > 0
              and not att.attisdropped
        ), '')
    from tables as t

    union all
    select 60, string_agg(
        format('CREATE POLICY %I ON public.%I AS %s FOR %s TO %s%s%s;',
               p.policyname, p.tablename, p.permissive, p.cmd,
               (select string_agg(
                    case when r::text = 'public' then 'PUBLIC' else quote_ident(r::text) end,
                    ', ')
                from unnest(p.roles) as r),
               case when p.qual is not null then E'\\n    USING (' || p.qual || ')' else '' end,
               case when p.with_check is not null
                    then E'\\n    WITH CHECK (' || p.with_check || ')' else '' end),
        E'\\n' order by p.tablename, p.policyname)
    from pg_catalog.pg_policies as p
    where p.schemaname = 'public'
      and p.tablename = any (array[{table_array}])

    union all
    select 99, 'COMMIT;'
)
select string_agg(body, E'\\n\\n' order by ord) as undo_sql
from parts;
"""
TABLES = tables
SIGNATURES = signatures

if __name__ == "__main__":
    print(QUERY)
