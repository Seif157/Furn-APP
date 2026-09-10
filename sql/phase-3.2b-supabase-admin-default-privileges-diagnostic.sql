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
            WHEN 'r' THEN 'table'
            WHEN 'S' THEN 'sequence'
            WHEN 'f' THEN 'function'
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
      AND defaults.defaclobjtype IN ('r', 'S', 'f')
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
    NULL::boolean AS can_alter_supabase_admin_defaults
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
    authority.can_alter_supabase_admin_defaults
FROM authority
ORDER BY record_type, schema_scope, object_type, grantee_name, privilege_type;
