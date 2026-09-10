/*
Phase 3.2B helper-function diagnostic.

Run this read-only statement before and after the migration. It captures the
exact deployed definitions, signatures, execution context, search path, owner,
and client execution privileges without reading application rows.
*/

WITH expected_functions(function_name, display_order) AS (
    VALUES
        ('is_admin'::name, 1),
        ('current_marketplace_party_id'::name, 2),
        ('current_party_is_approved'::name, 3)
),
client_roles AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (
            SELECT oid FROM pg_catalog.pg_roles
            WHERE rolname = 'authenticated'
        ) AS authenticated_oid,
        (
            SELECT oid FROM pg_catalog.pg_roles
            WHERE rolname = 'service_role'
        ) AS service_role_oid
)
SELECT
    expected.display_order,
    expected.function_name AS expected_function_name,
    function_row.oid IS NOT NULL AS function_present,
    pg_catalog.pg_get_function_identity_arguments(function_row.oid)
        AS identity_arguments,
    pg_catalog.pg_get_function_result(function_row.oid) AS result_type,
    language_row.lanname AS language_name,
    pg_catalog.pg_get_userbyid(function_row.proowner) AS owner_name,
    function_row.provolatile = 's' AS stable,
    function_row.prosecdef AS security_definer,
    (
        SELECT regexp_replace(setting, '^search_path=', '')
        FROM unnest(function_row.proconfig) AS setting
        WHERE setting LIKE 'search_path=%'
        LIMIT 1
    ) AS configured_search_path,
    EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                function_row.proacl,
                pg_catalog.acldefault('f', function_row.proowner)
            )
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
    ) AS public_execute,
    pg_catalog.has_function_privilege(
        roles.anon_oid,
        function_row.oid,
        'EXECUTE'
    ) AS anon_execute,
    pg_catalog.has_function_privilege(
        roles.authenticated_oid,
        function_row.oid,
        'EXECUTE'
    ) AS authenticated_execute,
    pg_catalog.has_function_privilege(
        roles.service_role_oid,
        function_row.oid,
        'EXECUTE'
    ) AS service_role_execute,
    pg_catalog.pg_get_functiondef(function_row.oid) AS function_definition
FROM expected_functions AS expected
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.proname = expected.function_name
   AND function_row.pronamespace = 'public'::regnamespace
LEFT JOIN pg_catalog.pg_language AS language_row
    ON language_row.oid = function_row.prolang
CROSS JOIN client_roles AS roles
ORDER BY expected.display_order, identity_arguments;
