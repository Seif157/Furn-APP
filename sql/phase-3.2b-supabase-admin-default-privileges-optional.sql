/*
OPTIONAL MANAGED-ROLE MIGRATION - NOT PART OF THE CORE PHASE 3.2B DEPLOYMENT.

Do not run until the companion read-only diagnostic has been reviewed and this
exact scope has passed in staging. The live audit found public-schema table,
sequence, and function rows and no global function row.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $phase32b_managed_defaults_preflight$
DECLARE
    current_role_is_superuser boolean;
    required_role name;
    default_expectation record;
BEGIN
    FOREACH required_role IN ARRAY ARRAY[
        'anon'::name,
        'authenticated'::name,
        'service_role'::name,
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

    IF pg_catalog.pg_has_role('anon', 'service_role', 'MEMBER')
       OR pg_catalog.pg_has_role('authenticated', 'service_role', 'MEMBER')
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults: client role must not inherit or assume service_role';
    END IF;

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
              defaults.defaclobjtype IN (
                  'r'::pg_catalog."char",
                  'S'::pg_catalog."char",
                  'f'::pg_catalog."char"
              )
              AND namespace.nspname IS DISTINCT FROM 'public'
              AND NOT (
                  defaults.defaclobjtype = 'f'::pg_catalog."char"
                  AND defaults.defaclnamespace = 0
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults: namespace scope drift';
    END IF;

    FOR default_expectation IN
        SELECT *
        FROM (VALUES
            ('r'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('r'::pg_catalog."char", 'public'::name, 'authenticated'::name),
            ('S'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('S'::pg_catalog."char", 'public'::name, 'authenticated'::name),
            ('f'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('f'::pg_catalog."char", 'public'::name, 'authenticated'::name)
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
                  default_expectation.object_type <>
                      'f'::pg_catalog."char"
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

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

-- PostgreSQL's implicit PUBLIC function EXECUTE is global. The separate global
-- revoke is needed because a schema-local default cannot subtract from it.
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
GRANT EXECUTE ON FUNCTIONS TO service_role;

DO $phase32b_managed_defaults_postflight$
DECLARE
    owner_role_oid oid;
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
BEGIN
    SELECT oid INTO STRICT owner_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'supabase_admin';
    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon';
    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'authenticated';
    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role';

    IF pg_catalog.pg_has_role('anon', 'service_role', 'MEMBER')
       OR pg_catalog.pg_has_role('authenticated', 'service_role', 'MEMBER')
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults postflight: client role inherits or can assume service_role';
    END IF;

    -- Missing rows are valid after REVOKE. Compute the effective ACL from the
    -- hard-wired/global default plus any schema-local additions instead.
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('public_tables'::text, 'r'::pg_catalog."char", 'r'::pg_catalog."char", 'public'::name),
            ('public_sequences'::text, 'S'::pg_catalog."char", 's'::pg_catalog."char", 'public'::name),
            ('public_functions'::text, 'f'::pg_catalog."char", 'f'::pg_catalog."char", 'public'::name),
            ('global_functions'::text, 'f'::pg_catalog."char", 'f'::pg_catalog."char", NULL::name)
        ) AS expected(
            scope_name,
            catalog_object_type,
            acldefault_object_type,
            schema_name
        )
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.nspname = expected.schema_name
        LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
            ON global_defaults.defaclrole = owner_role_oid
           AND global_defaults.defaclobjtype = expected.catalog_object_type
           AND global_defaults.defaclnamespace = 0
        LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
            ON schema_defaults.defaclrole = owner_role_oid
           AND schema_defaults.defaclobjtype = expected.catalog_object_type
           AND schema_defaults.defaclnamespace = namespace.oid
           AND expected.schema_name IS NOT NULL
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                global_defaults.defaclacl,
                pg_catalog.acldefault(
                    expected.acldefault_object_type,
                    owner_role_oid
                )
            ) || CASE
                WHEN expected.schema_name IS NULL
                THEN ARRAY[]::aclitem[]
                ELSE COALESCE(
                    schema_defaults.defaclacl,
                    ARRAY[]::aclitem[]
                )
            END
        ) AS acl
        WHERE CASE
            WHEN acl.grantee = 0 THEN true
            ELSE pg_catalog.pg_has_role(
                anon_role_oid,
                acl.grantee,
                'USAGE'
            ) OR pg_catalog.pg_has_role(
                authenticated_role_oid,
                acl.grantee,
                'USAGE'
            )
        END
          AND (
              expected.catalog_object_type IN (
                  'r'::pg_catalog."char",
                  'S'::pg_catalog."char"
              )
              OR acl.privilege_type = 'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults postflight: unsafe effective default privilege';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('public_functions'::text, 'public'::name),
            ('global_functions'::text, NULL::name)
        ) AS expected(scope_name, schema_name)
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.nspname = expected.schema_name
        LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
            ON global_defaults.defaclrole = owner_role_oid
           AND global_defaults.defaclobjtype = 'f'::pg_catalog."char"
           AND global_defaults.defaclnamespace = 0
        LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
            ON schema_defaults.defaclrole = owner_role_oid
           AND schema_defaults.defaclobjtype = 'f'::pg_catalog."char"
           AND schema_defaults.defaclnamespace = namespace.oid
           AND expected.schema_name IS NOT NULL
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    global_defaults.defaclacl,
                    pg_catalog.acldefault(
                        'f'::pg_catalog."char",
                        owner_role_oid
                    )
                ) || CASE
                    WHEN expected.schema_name IS NULL
                    THEN ARRAY[]::aclitem[]
                    ELSE COALESCE(
                        schema_defaults.defaclacl,
                        ARRAY[]::aclitem[]
                    )
                END
            ) AS acl
            WHERE acl.grantee = service_role_oid
              AND acl.privilege_type = 'EXECUTE'
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B optional defaults postflight: explicit service_role future-function EXECUTE missing';
    END IF;
END
$phase32b_managed_defaults_postflight$;

COMMIT;
