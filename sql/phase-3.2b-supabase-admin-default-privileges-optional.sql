/*
OPTIONAL MANAGED-ROLE MIGRATION - NOT PART OF THE CORE PHASE 3.2B DEPLOYMENT.

Do not run until the companion read-only diagnostic has been reviewed and this
exact scope has passed in staging. Any global table/sequence or schema-local
function client grant is treated as drift and aborts before changes.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';

DO $phase32b_managed_defaults_preflight$
DECLARE
    current_role_is_superuser boolean;
    required_role name;
    default_expectation record;
BEGIN
    FOREACH required_role IN ARRAY ARRAY[
        'anon'::name,
        'authenticated'::name,
        'supabase_admin'::name
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = required_role
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B optional defaults: missing role %s',
                    required_role
                );
        END IF;
    END LOOP;

    SELECT role_row.rolsuper
    INTO current_role_is_superuser
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = current_user;

    IF NOT (
        COALESCE(current_role_is_superuser, false)
        OR pg_catalog.pg_has_role(current_user, 'supabase_admin', 'MEMBER')
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults: insufficient supabase_admin authority';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_default_acl AS defaults
        JOIN pg_catalog.pg_roles AS owner_role
            ON owner_role.oid = defaults.defaclrole
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = defaults.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE owner_role.rolname = 'supabase_admin'
          AND COALESCE(grantee.rolname, 'PUBLIC')
              IN ('PUBLIC', 'anon', 'authenticated')
          AND (
              (defaults.defaclobjtype IN ('r', 'S')
               AND namespace.nspname IS DISTINCT FROM 'public')
              OR (defaults.defaclobjtype = 'f' AND defaults.defaclnamespace <> 0)
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults: namespace scope drift';
    END IF;

    FOR default_expectation IN
        SELECT *
        FROM (VALUES
            ('r'::char, 'public'::name, 'anon'::name),
            ('r'::char, 'public'::name, 'authenticated'::name),
            ('S'::char, 'public'::name, 'anon'::name),
            ('S'::char, 'public'::name, 'authenticated'::name),
            ('f'::char, NULL::name, 'PUBLIC'::name),
            ('f'::char, NULL::name, 'anon'::name),
            ('f'::char, NULL::name, 'authenticated'::name)
        ) AS expected(object_type, schema_name, grantee_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_default_acl AS defaults
            JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = defaults.defaclrole
            LEFT JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = defaults.defaclnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
            WHERE owner_role.rolname = 'supabase_admin'
              AND defaults.defaclobjtype = default_expectation.object_type
              AND namespace.nspname IS NOT DISTINCT FROM
                  default_expectation.schema_name
              AND COALESCE(grantee.rolname, 'PUBLIC') =
                  default_expectation.grantee_name
              AND (
                  default_expectation.object_type <> 'f'
                  OR acl.privilege_type = 'EXECUTE'
              )
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B optional defaults: expected ACL absent type=%s scope=%s grantee=%s',
                    default_expectation.object_type,
                    COALESCE(default_expectation.schema_name, '<all_schemas>'),
                    default_expectation.grantee_name
                );
        END IF;
    END LOOP;
END
$phase32b_managed_defaults_preflight$;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;

-- PostgreSQL's implicit PUBLIC function EXECUTE is global. A schema-local
-- revoke cannot subtract a privilege inherited from that global default.
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMIT;
