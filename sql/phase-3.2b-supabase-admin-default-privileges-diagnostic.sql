/*
Phase 3.2B managed-role default-privilege diagnostic.

READ ONLY. Run and review this metadata in staging before considering the
separate optional supabase_admin migration. It does not read application rows.
*/

WITH default_acl AS (
    SELECT
        owner_role.rolname AS owner_name,
        defaults.defaclnamespace,
        COALESCE(namespace.nspname, '<all_schemas>') AS schema_scope,
        defaults.defaclobjtype,
        CASE defaults.defaclobjtype
            WHEN 'r'::pg_catalog."char" THEN 'table'
            WHEN 'S'::pg_catalog."char" THEN 'sequence'
            WHEN 'f'::pg_catalog."char" THEN 'function'
            ELSE defaults.defaclobjtype::text
        END AS object_type,
        CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END
            AS grantee_name,
        acl.privilege_type,
        acl.is_grantable
    FROM pg_catalog.pg_default_acl AS defaults
    JOIN pg_catalog.pg_roles AS owner_role
        ON owner_role.oid = defaults.defaclrole
    LEFT JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = defaults.defaclnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE owner_role.rolname = 'supabase_admin'
      AND defaults.defaclobjtype IN (
          'r'::pg_catalog."char",
          'S'::pg_catalog."char",
          'f'::pg_catalog."char"
      )
),
managed_role AS (
    SELECT oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'supabase_admin'
),
expected_scopes(
    scope_name,
    catalog_object_type,
    acldefault_object_type,
    schema_name
) AS (
    VALUES
        ('public_tables'::text, 'r'::pg_catalog."char", 'r'::pg_catalog."char", 'public'::name),
        ('public_sequences'::text, 'S'::pg_catalog."char", 's'::pg_catalog."char", 'public'::name),
        ('public_functions'::text, 'f'::pg_catalog."char", 'f'::pg_catalog."char", 'public'::name),
        ('global_functions'::text, 'f'::pg_catalog."char", 'f'::pg_catalog."char", NULL::name)
),
effective_scopes AS (
    SELECT
        expected.scope_name,
        expected.schema_name,
        expected.catalog_object_type AS object_type,
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    global_defaults.defaclacl,
                    pg_catalog.acldefault(
                        expected.acldefault_object_type,
                        owner.oid
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
            LEFT JOIN pg_catalog.pg_roles AS grantee
                ON grantee.oid = acl.grantee
            WHERE COALESCE(grantee.rolname, 'PUBLIC')
                IN ('PUBLIC', 'anon', 'authenticated')
              AND (
                   expected.catalog_object_type IN (
                      'r'::pg_catalog."char",
                      'S'::pg_catalog."char"
                  )
                  OR acl.privilege_type = 'EXECUTE'
              )
        ) AS check_passed
    FROM expected_scopes AS expected
    CROSS JOIN managed_role AS owner
    LEFT JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.nspname = expected.schema_name
    LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
        ON global_defaults.defaclrole = owner.oid
       AND global_defaults.defaclobjtype = expected.catalog_object_type
       AND global_defaults.defaclnamespace = 0
    LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
        ON schema_defaults.defaclrole = owner.oid
       AND schema_defaults.defaclobjtype = expected.catalog_object_type
       AND schema_defaults.defaclnamespace = namespace.oid
       AND expected.schema_name IS NOT NULL
),
authority AS (
    SELECT
        current_user AS deployment_role,
        role_row.oid IS NOT NULL AS supabase_admin_present,
        COALESCE(current_role_row.rolsuper, false)
            OR CASE WHEN role_row.oid IS NULL THEN false
                ELSE pg_catalog.pg_has_role(
                    current_user,
                    role_row.oid,
                    'MEMBER'
                )
            END AS can_alter_supabase_admin_defaults
    FROM (VALUES ('supabase_admin'::name)) AS expected(role_name)
    LEFT JOIN pg_catalog.pg_roles AS role_row
        ON role_row.rolname = expected.role_name
    LEFT JOIN pg_catalog.pg_roles AS current_role_row
        ON current_role_row.rolname = current_user
)
SELECT
    'default_acl'::text AS record_type,
    defaults.owner_name,
    defaults.schema_scope,
    defaults.object_type,
    defaults.grantee_name,
    defaults.privilege_type,
    defaults.is_grantable,
    NULL::name AS deployment_role,
    NULL::boolean AS supabase_admin_present,
    NULL::boolean AS can_alter_supabase_admin_defaults,
    NULL::boolean AS check_passed
FROM default_acl AS defaults
UNION ALL
SELECT
    'authority'::text,
    'supabase_admin'::name,
    NULL::name,
    NULL::text,
    NULL::name,
    NULL::text,
    NULL::boolean,
    authority.deployment_role,
    authority.supabase_admin_present,
    authority.can_alter_supabase_admin_defaults,
    NULL::boolean
FROM authority
UNION ALL
SELECT
    'effective_future_privilege'::text,
    'supabase_admin'::name,
    COALESCE(effective.schema_name, '<all_schemas>'::name),
    effective.scope_name,
    NULL::name,
    NULL::text,
    NULL::boolean,
    NULL::name,
    true,
    NULL::boolean,
    effective.check_passed
FROM effective_scopes AS effective
ORDER BY record_type, schema_scope, object_type, grantee_name, privilege_type;
