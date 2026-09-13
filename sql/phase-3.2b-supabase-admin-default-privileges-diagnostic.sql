/*
Phase 3.2B managed-role default-privilege diagnostic.

READ ONLY. Run and review this metadata in staging before considering the
separate optional supabase_admin migration. It does not read application rows.
The default-ACL rowset deliberately has no owner, namespace, object-type, or
grantee filter: PUBLIC, anon, authenticated, service_role, and any unexpected
role remain visible. service_role is a managed elevated server role, not a
client role. The authority and effective-scope rows remain specific to the
separate optional supabase_admin migration.
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
),
managed_role AS (
    SELECT oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'supabase_admin'
),
resolved_roles AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (
            SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'authenticated'
        ) AS authenticated_oid,
        (
            SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'service_role'
        ) AS service_role_oid
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
        roles.anon_oid IS NOT NULL
            AND roles.authenticated_oid IS NOT NULL
            AND roles.service_role_oid IS NOT NULL
            AND NOT pg_catalog.pg_has_role(
                roles.anon_oid,
                roles.service_role_oid,
                'MEMBER'
            )
            AND NOT pg_catalog.pg_has_role(
                roles.authenticated_oid,
                roles.service_role_oid,
                'MEMBER'
            ) AS client_roles_separate,
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
            WHERE CASE
                WHEN acl.grantee = 0 THEN true
                ELSE pg_catalog.pg_has_role(
                    roles.anon_oid,
                    acl.grantee,
                    'USAGE'
                ) OR pg_catalog.pg_has_role(
                    roles.authenticated_oid,
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
        ) AS no_effective_client_default,
        expected.catalog_object_type = 'f'::pg_catalog."char"
            AS service_role_execute_expected,
        EXISTS (
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
            WHERE acl.grantee = roles.service_role_oid
              AND acl.privilege_type = 'EXECUTE'
        ) AS service_role_execute_effective
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
    CROSS JOIN resolved_roles AS roles
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
    NULL::boolean AS client_roles_separate,
    NULL::boolean AS no_effective_client_default,
    NULL::boolean AS service_role_execute_expected,
    NULL::boolean AS service_role_execute_effective,
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
    NULL::boolean,
    NULL::boolean,
    NULL::boolean,
    NULL::boolean,
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
    effective.client_roles_separate,
    effective.no_effective_client_default,
    effective.service_role_execute_expected,
    effective.service_role_execute_effective,
    effective.client_roles_separate
        AND effective.no_effective_client_default
        AND (
            NOT effective.service_role_execute_expected
            OR effective.service_role_execute_effective
        )
FROM effective_scopes AS effective
ORDER BY record_type, schema_scope, object_type, grantee_name, privilege_type;
