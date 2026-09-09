/*
Phase 3.2B post-migration verification.

Run each numbered SELECT separately after a reviewed migration is applied. Every
statement reads PostgreSQL metadata only; none reads application rows.
*/

-- 01. RLS must remain enabled on every public base/partitioned table.
SELECT
    relation.relname AS table_name,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS rls_forced,
    relation.relrowsecurity AS check_passed
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
ORDER BY relation.relname;


-- 02. marketplace_party INSERT/UPDATE column boundaries.
WITH requested_roles(role_name, display_order) AS (
    VALUES
        ('anon'::text, 1),
        ('authenticated'::text, 2),
        ('service_role'::text, 3)
),
resolved_roles AS (
    SELECT
        requested.role_name,
        requested.display_order,
        role_row.oid AS role_oid
    FROM requested_roles AS requested
    LEFT JOIN pg_catalog.pg_roles AS role_row
        ON role_row.rolname = requested.role_name
),
target_table AS (
    SELECT relation.oid AS table_oid
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'marketplace_party'
      AND relation.relkind IN ('r', 'p')
),
target_columns(column_name, authenticated_insert_expected) AS (
    VALUES
        ('id'::name, false),
        ('user_id'::name, true),
        ('business_name'::name, true),
        ('business_description'::name, true),
        ('logo_url'::name, true),
        ('coverage_area'::name, true),
        ('approval_state'::name, false),
        ('state_reason'::name, false)
),
actual AS (
    SELECT
        role_row.role_name,
        role_row.display_order,
        column_row.column_name,
        column_row.authenticated_insert_expected,
        CASE
            WHEN role_row.role_oid IS NULL THEN NULL
            ELSE pg_catalog.has_table_privilege(
                role_row.role_oid,
                target.table_oid,
                'INSERT'
            )
        END AS table_insert,
        CASE
            WHEN role_row.role_oid IS NULL THEN NULL
            ELSE pg_catalog.has_column_privilege(
                role_row.role_oid,
                target.table_oid,
                column_row.column_name,
                'INSERT'
            )
        END AS column_insert,
        CASE
            WHEN role_row.role_oid IS NULL THEN NULL
            ELSE pg_catalog.has_column_privilege(
                role_row.role_oid,
                target.table_oid,
                column_row.column_name,
                'UPDATE'
            )
        END AS column_update
    FROM resolved_roles AS role_row
    CROSS JOIN target_table AS target
    CROSS JOIN target_columns AS column_row
)
SELECT
    role_name,
    column_name,
    table_insert,
    column_insert,
    column_update,
    CASE
        WHEN role_name = 'anon'
        THEN NOT COALESCE(column_insert, true)
             AND NOT COALESCE(column_update, true)
        WHEN role_name = 'authenticated'
        THEN column_insert = authenticated_insert_expected
             AND (
                 column_name NOT IN ('approval_state', 'state_reason')
                 OR NOT COALESCE(column_update, true)
             )
        WHEN role_name = 'service_role'
        THEN COALESCE(column_insert, false)
             AND COALESCE(column_update, false)
        ELSE false
    END AS check_passed
FROM actual
ORDER BY display_order, column_name;


-- 03. The authenticated seller INSERT policy must enforce identity, pending
-- state, and a null reason. This returns policy metadata, never party rows.
WITH authenticated_role AS (
    SELECT oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'authenticated'
),
insert_policies AS (
    SELECT
        policy.polname,
        pg_catalog.pg_get_expr(
            policy.polwithcheck,
            policy.polrelid,
            true
        ) AS check_expression
    FROM pg_catalog.pg_policy AS policy
    CROSS JOIN authenticated_role AS role_row
    WHERE policy.polrelid = 'public.marketplace_party'::regclass
      AND policy.polcmd = 'a'
      AND (
          0 = ANY(policy.polroles)
          OR role_row.oid = ANY(policy.polroles)
      )
)
SELECT
    polname AS policy_name,
    check_expression AS with_check_expression,
    check_expression ~* 'user_id.*auth\.uid'
        AS enforces_authenticated_user,
    check_expression ~* 'approval_state.*pending'
        AS enforces_pending_state,
    check_expression ~* 'state_reason.*IS NULL'
        AS enforces_null_reason,
    check_expression ~* 'user_id.*auth\.uid'
        AND check_expression ~* 'approval_state.*pending'
        AND check_expression ~* 'state_reason.*IS NULL'
        AS check_passed
FROM insert_policies
ORDER BY polname;


-- 04. Financial view must be invoker-rights and unavailable to PUBLIC/anon.
WITH target_view AS (
    SELECT relation.*
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'order_financial_position'
      AND relation.relkind = 'v'
),
roles AS (
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
    view_row.relname AS view_name,
    COALESCE(
        view_row.reloptions @> ARRAY['security_invoker=true'],
        false
    ) AS security_invoker,
    EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                view_row.relacl,
                pg_catalog.acldefault('r', view_row.relowner)
            )
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'SELECT'
    ) AS public_direct_select,
    pg_catalog.has_table_privilege(
        roles.anon_oid,
        view_row.oid,
        'SELECT'
    ) AS anon_select,
    pg_catalog.has_table_privilege(
        roles.authenticated_oid,
        view_row.oid,
        'SELECT'
    ) AS authenticated_select,
    pg_catalog.has_table_privilege(
        roles.service_role_oid,
        view_row.oid,
        'SELECT'
    ) AS service_role_select,
    COALESCE(
        view_row.reloptions @> ARRAY['security_invoker=true'],
        false
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                view_row.relacl,
                pg_catalog.acldefault('r', view_row.relowner)
            )
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'SELECT'
    )
    AND NOT pg_catalog.has_table_privilege(
        roles.anon_oid,
        view_row.oid,
        'SELECT'
    )
    AND pg_catalog.has_table_privilege(
        roles.authenticated_oid,
        view_row.oid,
        'SELECT'
    )
    AND pg_catalog.has_table_privilege(
        roles.service_role_oid,
        view_row.oid,
        'SELECT'
    ) AS check_passed
FROM target_view AS view_row
CROSS JOIN roles;


-- 05. Phase 3.2B catalog read policies and their complete predicates.
SELECT
    policy.tablename AS table_name,
    policy.policyname AS policy_name,
    policy.permissive,
    policy.roles,
    policy.cmd AS command,
    policy.qual AS using_expression,
    CASE
        WHEN policy.policyname = 'phase32b_category_anon_read_guard'
        THEN policy.qual ~* 'is_active.*true'
        WHEN policy.policyname = 'phase32b_category_authenticated_read_guard'
        THEN policy.qual ~* 'is_active.*true'
             AND policy.qual ~* 'is_admin'
        WHEN policy.policyname IN (
            'phase32b_product_anon_read_guard',
            'phase32b_product_authenticated_read_guard'
        )
        THEN policy.qual ~* 'lifecycle_state.*published'
             AND policy.qual ~* 'approval_state.*approved'
             AND policy.qual ~* 'is_active.*true'
        WHEN policy.policyname IN (
            'phase32b_enrichment_anon_read_guard',
            'phase32b_enrichment_authenticated_read_guard'
        )
        THEN policy.qual ~* 'confirmation_state.*party_confirmed'
        WHEN policy.policyname LIKE 'phase32b%read_guard'
        THEN policy.qual ~* 'public\.product'
        ELSE true
    END AS predicate_check_passed,
    policy.permissive = 'RESTRICTIVE' AS restrictive_check_passed
FROM pg_catalog.pg_policies AS policy
WHERE policy.schemaname = 'public'
  AND policy.policyname IN (
      'phase32b_category_anon_read_guard',
      'phase32b_category_authenticated_read_guard',
      'phase32b_product_anon_read_guard',
      'phase32b_product_authenticated_read_guard',
      'phase32b_product_color_read_guard',
      'phase32b_product_image_read_guard',
      'phase32b_product_3d_model_read_guard',
      'phase32b_enrichment_anon_read_guard',
      'phase32b_enrichment_authenticated_read_guard'
  )
ORDER BY policy.tablename, policy.policyname;


-- 06. Every child write operation must be a restrictive approved-owner/admin
-- guard. A safe result has twelve rows and check_passed = true for every row.
SELECT
    policy.tablename AS table_name,
    policy.policyname AS policy_name,
    policy.cmd AS command,
    policy.qual AS using_expression,
    policy.with_check AS with_check_expression,
    policy.permissive = 'RESTRICTIVE'
    AND policy.cmd IN ('INSERT', 'UPDATE', 'DELETE')
    AND lower(concat_ws(' ', policy.qual, policy.with_check))
        ~ 'current_party_is_approved'
    AND lower(concat_ws(' ', policy.qual, policy.with_check))
        ~ 'current_marketplace_party_id'
    AND lower(concat_ws(' ', policy.qual, policy.with_check))
        ~ 'is_admin'
    AS check_passed
FROM pg_catalog.pg_policies AS policy
WHERE policy.schemaname = 'public'
  AND policy.tablename IN (
      'product_color',
      'product_image',
      'product_3d_model',
      'product_enrichment_assignment'
  )
  AND policy.policyname LIKE 'phase32b%guard'
  AND policy.cmd IN ('INSERT', 'UPDATE', 'DELETE')
ORDER BY policy.tablename, policy.cmd;


-- 07. Helper boundary. Until exact bodies are reviewed and a follow-up is
-- applied, hardened_check_passed is expected to remain false and blocks final
-- Phase 3.2B sign-off.
WITH expected_functions(function_name) AS (
    VALUES
        ('is_admin'::name),
        ('current_marketplace_party_id'::name),
        ('current_party_is_approved'::name)
),
roles AS (
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
    expected.function_name,
    function_row.oid IS NOT NULL AS function_present,
    pg_catalog.pg_get_function_identity_arguments(function_row.oid)
        AS identity_arguments,
    pg_catalog.pg_get_userbyid(function_row.proowner) AS owner_name,
    function_row.prosecdef AS security_definer,
    function_row.provolatile = 's' AS stable,
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
    pg_catalog.pg_get_userbyid(function_row.proowner) = 'postgres'
    AND function_row.prosecdef
    AND function_row.provolatile = 's'
    AND COALESCE(
        EXISTS (
            SELECT 1
            FROM unnest(function_row.proconfig) AS setting
            WHERE regexp_replace(setting, '^search_path=', '') IN ('', '""')
        ),
        false
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                function_row.proacl,
                pg_catalog.acldefault('f', function_row.proowner)
            )
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
    )
    AND NOT pg_catalog.has_function_privilege(
        roles.anon_oid,
        function_row.oid,
        'EXECUTE'
    )
    AND pg_catalog.has_function_privilege(
        roles.authenticated_oid,
        function_row.oid,
        'EXECUTE'
    )
    AND pg_catalog.has_function_privilege(
        roles.service_role_oid,
        function_row.oid,
        'EXECUTE'
    ) AS hardened_check_passed
FROM expected_functions AS expected
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.proname = expected.function_name
   AND function_row.pronamespace = 'public'::regnamespace
CROSS JOIN roles
ORDER BY expected.function_name, identity_arguments;


-- 08. Dangerous existing grants. A safe result is empty.
WITH target_roles AS (
    SELECT oid, rolname
    FROM pg_catalog.pg_roles
    WHERE rolname IN ('anon', 'authenticated')
),
dangerous_privileges(role_name, privilege_name) AS (
    VALUES
        ('anon'::name, 'INSERT'::text),
        ('anon'::name, 'UPDATE'::text),
        ('anon'::name, 'DELETE'::text),
        ('anon'::name, 'TRUNCATE'::text),
        ('anon'::name, 'REFERENCES'::text),
        ('anon'::name, 'TRIGGER'::text),
        ('anon'::name, 'MAINTAIN'::text),
        ('authenticated'::name, 'TRUNCATE'::text),
        ('authenticated'::name, 'REFERENCES'::text),
        ('authenticated'::name, 'TRIGGER'::text),
        ('authenticated'::name, 'MAINTAIN'::text)
),
public_tables AS (
    SELECT relation.oid, relation.relname
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
)
SELECT
    table_row.relname AS table_name,
    role_row.rolname AS role_name,
    privilege.privilege_name,
    false AS check_passed
FROM public_tables AS table_row
CROSS JOIN target_roles AS role_row
JOIN dangerous_privileges AS privilege
    ON privilege.role_name = role_row.rolname
WHERE pg_catalog.has_table_privilege(
    role_row.oid,
    table_row.oid,
    privilege.privilege_name
)
ORDER BY table_row.relname, role_row.rolname, privilege.privilege_name;


-- 09. Unsafe automatic grants for future public objects. Safe result: empty.
SELECT
    owner_role.rolname AS owner_name,
    CASE defaults.defaclobjtype
        WHEN 'r' THEN 'table'
        WHEN 'S' THEN 'sequence'
        WHEN 'f' THEN 'function'
        ELSE defaults.defaclobjtype::text
    END AS object_type,
    CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END
        AS grantee_name,
    acl.privilege_type,
    false AS check_passed
FROM pg_catalog.pg_default_acl AS defaults
JOIN pg_catalog.pg_roles AS owner_role
    ON owner_role.oid = defaults.defaclrole
LEFT JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = defaults.defaclnamespace
CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
WHERE owner_role.rolname IN ('postgres', 'supabase_admin')
  AND (namespace.nspname = 'public' OR defaults.defaclnamespace = 0)
  AND COALESCE(grantee.rolname, 'PUBLIC')
      IN ('PUBLIC', 'anon', 'authenticated')
  AND (
      defaults.defaclobjtype IN ('r', 'S')
      OR (
          defaults.defaclobjtype = 'f'
          AND acl.privilege_type = 'EXECUTE'
      )
  )
ORDER BY owner_name, object_type, grantee_name, acl.privilege_type;


-- 10. No RLS-enabled table may unexpectedly lose every policy. Safe: empty.
SELECT
    relation.relname AS table_name,
    false AS check_passed
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
  AND relation.relrowsecurity
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_policy AS policy
      WHERE policy.polrelid = relation.oid
  )
ORDER BY relation.relname;
