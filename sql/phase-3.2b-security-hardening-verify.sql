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
WITH requested_roles(role_name, display_order, table_insert_expected, table_update_expected) AS (
    VALUES
        ('anon'::text, 1, false, false),
        ('authenticated'::text, 2, false, false),
        ('service_role'::text, 3, true, true)
),
resolved_roles AS (
    SELECT
        requested.role_name,
        requested.display_order,
        requested.table_insert_expected,
        requested.table_update_expected,
        role_row.oid AS role_oid
    FROM requested_roles AS requested
    LEFT JOIN pg_catalog.pg_roles AS role_row
        ON role_row.rolname = requested.role_name
),
target_table AS (
    SELECT (
        SELECT relation.oid
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'marketplace_party'
          AND relation.relkind IN ('r', 'p')
    ) AS table_oid
),
target_columns(
    column_name,
    authenticated_insert_expected,
    authenticated_update_expected
) AS (
    VALUES
        ('id'::name, false, false),
        ('user_id'::name, true, false),
        ('business_name'::name, true, true),
        ('business_description'::name, true, true),
        ('logo_url'::name, true, true),
        ('coverage_area'::name, true, true),
        ('approval_state'::name, false, false),
        ('state_reason'::name, false, false)
),
actual AS (
    SELECT
        role_row.role_name,
        role_row.display_order,
        role_row.role_oid,
        role_row.table_insert_expected,
        role_row.table_update_expected,
        target.table_oid,
        column_row.column_name,
        column_row.authenticated_insert_expected,
        column_row.authenticated_update_expected,
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
            ELSE pg_catalog.has_table_privilege(
                role_row.role_oid,
                target.table_oid,
                'UPDATE'
            )
        END AS table_update,
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
    role_oid IS NOT NULL AND table_oid IS NOT NULL AS object_present,
    role_name,
    column_name,
    table_insert_expected,
    table_insert,
    table_update_expected,
    table_update,
    CASE
        WHEN role_name = 'authenticated' THEN authenticated_insert_expected
        WHEN role_name = 'service_role' THEN true
        ELSE false
    END AS column_insert_expected,
    column_insert,
    CASE
        WHEN role_name = 'authenticated' THEN authenticated_update_expected
        WHEN role_name = 'service_role' THEN true
        ELSE false
    END AS column_update_expected,
    column_update,
    role_oid IS NOT NULL
        AND table_oid IS NOT NULL
        AND table_insert = table_insert_expected
        AND table_update = table_update_expected
        AND column_insert = CASE
            WHEN role_name = 'authenticated' THEN authenticated_insert_expected
            WHEN role_name = 'service_role' THEN true
            ELSE false
        END
        AND column_update = CASE
            WHEN role_name = 'authenticated' THEN authenticated_update_expected
            WHEN role_name = 'service_role' THEN true
            ELSE false
        END AS check_passed,
    CASE
        WHEN role_oid IS NULL THEN 'missing_expected_role'
        WHEN table_oid IS NULL THEN 'missing_marketplace_party_table'
        WHEN table_insert IS DISTINCT FROM table_insert_expected
          OR table_update IS DISTINCT FROM table_update_expected
        THEN 'table_write_privilege_mismatch'
        WHEN column_insert IS DISTINCT FROM CASE
            WHEN role_name = 'authenticated' THEN authenticated_insert_expected
            WHEN role_name = 'service_role' THEN true
            ELSE false
        END
        THEN 'column_insert_privilege_mismatch'
        WHEN column_update IS DISTINCT FROM CASE
            WHEN role_name = 'authenticated' THEN authenticated_update_expected
            WHEN role_name = 'service_role' THEN true
            ELSE false
        END
        THEN 'column_update_privilege_mismatch'
        ELSE 'ok'
    END AS finding_code
FROM actual
ORDER BY display_order, column_name;


-- 03. The authenticated seller INSERT policy must enforce identity, pending
-- state, and a null reason. The expected row remains visible if the policy is
-- missing, duplicated, or malformed.
WITH expected_objects(
    object_name,
    expected_role,
    expected_command,
    expected_permissive
) AS (
    VALUES (
        'marketplace_party_authenticated_insert'::text,
        'authenticated'::text,
        'INSERT'::text,
        'PERMISSIVE'::text
    )
),
actual_policies AS (
    SELECT
        policy.policyname,
        policy.permissive,
        policy.roles,
        policy.cmd,
        policy.qual,
        policy.with_check
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename = 'marketplace_party'
      AND policy.cmd = 'INSERT'
),
actual AS (
    SELECT
        count(*) AS actual_count,
        min(policyname::text) AS policy_name,
        min(permissive) AS permissive,
        string_agg(roles::text, ', ' ORDER BY policyname) AS actual_roles,
        min(cmd) AS command,
        min(qual) AS using_expression,
        min(with_check) AS check_expression
    FROM actual_policies
)
SELECT
    actual.actual_count = 1 AS object_present,
    expected.object_name,
    expected.expected_role,
    actual.actual_roles AS actual_role,
    expected.expected_command,
    actual.command AS actual_command,
    expected.expected_permissive,
    actual.permissive AS actual_permissive,
    actual.policy_name,
    actual.using_expression,
    actual.check_expression AS with_check_expression,
    actual.check_expression ~* 'user_id.*auth\.uid'
        AS enforces_authenticated_user,
    actual.check_expression ~* 'approval_state.*pending'
        AS enforces_pending_state,
    actual.check_expression ~* 'state_reason.*IS NULL'
        AS enforces_null_reason,
    actual.actual_count = 1
        AND actual.actual_roles = '{authenticated}'
        AND actual.command = expected.expected_command
        AND actual.permissive = expected.expected_permissive
        AND actual.using_expression IS NULL
        AND actual.check_expression ~* 'user_id.*auth\.uid'
        AND actual.check_expression ~* 'approval_state.*pending'
        AND actual.check_expression ~* 'state_reason.*IS NULL'
        AS check_passed,
    CASE
        WHEN actual.actual_count = 0 THEN 'missing_marketplace_party_insert_policy'
        WHEN actual.actual_count > 1 THEN 'duplicate_marketplace_party_insert_policy'
        WHEN actual.actual_roles IS DISTINCT FROM '{authenticated}'
        THEN 'marketplace_party_insert_role_mismatch'
        WHEN actual.command IS DISTINCT FROM expected.expected_command
        THEN 'marketplace_party_insert_command_mismatch'
        WHEN actual.permissive IS DISTINCT FROM expected.expected_permissive
        THEN 'marketplace_party_insert_mode_mismatch'
        WHEN actual.using_expression IS NOT NULL
          OR actual.check_expression !~* 'user_id.*auth\.uid'
          OR actual.check_expression !~* 'approval_state.*pending'
          OR actual.check_expression !~* 'state_reason.*IS NULL'
        THEN 'marketplace_party_insert_predicate_mismatch'
        ELSE 'ok'
    END AS finding_code
FROM expected_objects AS expected
LEFT JOIN actual ON true;


-- 04. Financial view must be invoker-rights and unavailable to PUBLIC/anon.
WITH expected_views(
    schema_name,
    view_name,
    expected_role,
    expected_command,
    expected_owner,
    expected_security_invoker
) AS (
    VALUES (
        'public'::name,
        'order_financial_position'::name,
        'authenticated, service_role'::text,
        'SELECT'::text,
        'postgres'::name,
        true
    )
),
actual_views AS (
    SELECT relation.*, namespace.nspname
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE relation.relkind = 'v'
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
),
exact_mixed(table_name, policy_name, expected_using_expression) AS (
    VALUES
        (
            'custom_offering'::name,
            'custom_offering_select_published_or_own'::name,
            $predicate$(publication_state = 'published'::public.custom_offering_state)
                OR (marketplace_party_id = public.current_marketplace_party_id())
                OR public.is_admin()$predicate$::text
        ),
        (
            'product'::name,
            'product_select_published_or_own'::name,
            $predicate$(lifecycle_state = 'published'::public.product_lifecycle_state)
                OR (marketplace_party_id = public.current_marketplace_party_id())
                OR public.is_admin()$predicate$::text
        ),
        (
            'product_color'::name,
            'product_color_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_color.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_image'::name,
            'product_image_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_image.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_3d_model'::name,
            'product_3d_model_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_3d_model.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_enrichment_assignment'::name,
            'product_enrichment_assignment_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id =
                    product_enrichment_assignment.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        )
),
comparison AS (
    SELECT
        expected.*,
        view_row.oid AS view_oid,
        view_row.relowner,
        view_row.relacl,
        view_row.reloptions,
        pg_catalog.pg_get_userbyid(view_row.relowner) AS actual_owner,
        COALESCE(
            view_row.reloptions @> ARRAY['security_invoker=true'],
            false
        ) AS actual_security_invoker,
        EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    view_row.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        view_row.relowner
                    )
                )
            ) AS acl
            WHERE acl.grantee = 0
              AND acl.privilege_type = 'SELECT'
        ) AS public_direct_select,
        CASE WHEN view_row.oid IS NULL OR roles.anon_oid IS NULL THEN NULL
            ELSE pg_catalog.has_table_privilege(
                roles.anon_oid,
                view_row.oid,
                'SELECT'
            )
        END AS anon_select,
        CASE
            WHEN view_row.oid IS NULL OR roles.authenticated_oid IS NULL THEN NULL
            ELSE pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                view_row.oid,
                'SELECT'
            )
        END AS authenticated_select,
        CASE
            WHEN view_row.oid IS NULL OR roles.service_role_oid IS NULL THEN NULL
            ELSE pg_catalog.has_table_privilege(
                roles.service_role_oid,
                view_row.oid,
                'SELECT'
            )
        END AS service_role_select,
        (
            SELECT string_agg(
                CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
                ', ' ORDER BY
                CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END
            )
            FROM pg_catalog.aclexplode(
                COALESCE(
                    view_row.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        view_row.relowner
                    )
                )
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
            WHERE acl.privilege_type = 'SELECT'
              AND acl.grantee <> view_row.relowner
        ) AS actual_roles
    FROM expected_views AS expected
    LEFT JOIN actual_views AS view_row
        ON view_row.nspname = expected.schema_name
       AND view_row.relname = expected.view_name
    CROSS JOIN roles
)
SELECT
    view_oid IS NOT NULL AS object_present,
    view_name,
    expected_role,
    actual_roles AS actual_role,
    expected_command,
    CASE WHEN view_oid IS NULL THEN NULL ELSE 'SELECT' END AS actual_command,
    expected_owner,
    actual_owner,
    expected_security_invoker,
    actual_security_invoker,
    public_direct_select,
    anon_select,
    authenticated_select,
    service_role_select,
    view_oid IS NOT NULL
        AND actual_owner = expected_owner
        AND actual_security_invoker = expected_security_invoker
        AND actual_roles = expected_role
        AND NOT public_direct_select
        AND NOT anon_select
        AND authenticated_select
        AND service_role_select AS check_passed,
    CASE
        WHEN view_oid IS NULL THEN 'missing_financial_view'
        WHEN actual_owner IS DISTINCT FROM expected_owner
        THEN 'financial_view_owner_mismatch'
        WHEN actual_security_invoker IS DISTINCT FROM expected_security_invoker
        THEN 'financial_view_security_mode_mismatch'
        WHEN actual_roles IS DISTINCT FROM expected_role
          OR public_direct_select
          OR anon_select
          OR NOT COALESCE(authenticated_select, false)
          OR NOT COALESCE(service_role_select, false)
        THEN 'financial_view_grant_mismatch'
        ELSE 'ok'
    END AS finding_code
FROM comparison;


-- 05. Phase 3.2B catalog read policies and their complete predicates.
WITH expected_policies(
    table_name,
    policy_name,
    expected_role,
    expected_command,
    expected_mode,
    predicate_kind
) AS (
    VALUES
        ('category'::name, 'phase32b_category_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'active'::text),
        ('category'::name, 'phase32b_category_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'active_admin'::text),
        ('custom_offering'::name, 'custom_offering_select_published_or_own'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'custom_mixed'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'custom_public'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'custom_public'::text),
        ('product'::name, 'product_select_published_or_own'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product'::name, 'phase32b_product_owner_read'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product'::name, 'phase32b_product_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'product_public'::text),
        ('product'::name, 'phase32b_product_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'product_public'::text),
        ('product'::name, 'phase32b_product_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'product_authenticated'::text),
        ('product_color'::name, 'product_color_select'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_color'::name, 'phase32b_product_color_owner_read'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_color'::name, 'phase32b_product_color_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'product_image_select'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_image'::name, 'phase32b_product_image_owner_read'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'phase32b_product_image_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'product_3d_model_select'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_owner_read'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_enrichment_assignment'::name, 'product_enrichment_assignment_select'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_owner_read'::name, 'authenticated'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read'::name, 'anon'::text, 'SELECT'::text, 'PERMISSIVE'::text, 'enrichment_public'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read_guard'::name, 'anon'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'enrichment_public'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_authenticated_read_guard'::name, 'authenticated'::text, 'SELECT'::text, 'RESTRICTIVE'::text, 'enrichment_authenticated'::text)
),
exact_mixed(table_name, policy_name, expected_using_expression) AS (
    VALUES
        (
            'custom_offering'::name,
            'custom_offering_select_published_or_own'::name,
            $predicate$(publication_state = 'published'::public.custom_offering_state)
                OR (marketplace_party_id = public.current_marketplace_party_id())
                OR public.is_admin()$predicate$::text
        ),
        (
            'product'::name,
            'product_select_published_or_own'::name,
            $predicate$(lifecycle_state = 'published'::public.product_lifecycle_state)
                OR (marketplace_party_id = public.current_marketplace_party_id())
                OR public.is_admin()$predicate$::text
        ),
        (
            'product_color'::name,
            'product_color_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_color.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_image'::name,
            'product_image_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_image.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_3d_model'::name,
            'product_3d_model_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id = product_3d_model.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        ),
        (
            'product_enrichment_assignment'::name,
            'product_enrichment_assignment_select'::name,
            $predicate$EXISTS (
                SELECT 1 FROM public.product AS parent_product
                WHERE parent_product.id =
                    product_enrichment_assignment.product_id
                  AND (
                      parent_product.lifecycle_state =
                          'published'::public.product_lifecycle_state
                      OR parent_product.marketplace_party_id =
                          public.current_marketplace_party_id()
                      OR public.is_admin()
                  )
            )$predicate$::text
        )
),
comparison AS (
    SELECT
        expected.*,
        actual.policyname AS actual_policy_name,
        array_to_string(actual.roles, ', ') AS actual_role,
        actual.cmd AS actual_command,
        actual.permissive AS actual_mode,
        actual.qual AS using_expression,
        CASE expected.predicate_kind
            WHEN 'active' THEN
                actual.qual ~* 'is_active.*true'
                AND lower(actual.qual) !~ 'is_admin|current_marketplace_party_id'
            WHEN 'active_admin' THEN
                actual.qual ~* 'is_active.*true'
                AND actual.qual ~* 'is_admin'
            WHEN 'custom_mixed' THEN
                pg_catalog.regexp_replace(
                    lower(actual.qual),
                    '[[:space:]]',
                    '',
                    'g'
                ) = pg_catalog.regexp_replace(
                    lower(exact.expected_using_expression),
                    '[[:space:]]',
                    '',
                    'g'
                )
            WHEN 'custom_public' THEN
                actual.qual ~* 'publication_state.*published'
                AND actual.qual ~* 'custom_offering_state'
                AND lower(actual.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'mixed_owner' THEN
                pg_catalog.regexp_replace(
                    lower(actual.qual),
                    '[[:space:]]',
                    '',
                    'g'
                ) = pg_catalog.regexp_replace(
                    lower(exact.expected_using_expression),
                    '[[:space:]]',
                    '',
                    'g'
                )
            WHEN 'owner' THEN
                lower(actual.qual) ~ 'current_marketplace_party_id|is_admin'
            WHEN 'product_public' THEN
                actual.qual ~* 'lifecycle_state.*published'
                AND actual.qual ~* 'approval_state.*approved'
                AND actual.qual ~* 'is_active.*true'
                AND lower(actual.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'product_authenticated' THEN
                actual.qual ~* 'lifecycle_state.*published'
                AND actual.qual ~* 'approval_state.*approved'
                AND actual.qual ~* 'is_active.*true'
                AND lower(actual.qual) ~ 'current_marketplace_party_id|is_admin'
            WHEN 'child_parent' THEN
                actual.qual ~* 'from[[:space:]]+(public\.)?product'
            WHEN 'enrichment_public' THEN
                actual.qual ~* 'confirmation_state.*party_confirmed'
                AND actual.qual ~* 'from[[:space:]]+(public\.)?product'
                AND lower(actual.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'enrichment_authenticated' THEN
                actual.qual ~* 'confirmation_state.*party_confirmed'
                AND lower(actual.qual) ~ 'current_marketplace_party_id|is_admin'
            ELSE false
        END AS predicate_check_passed
    FROM expected_policies AS expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = expected.table_name
       AND actual.policyname = expected.policy_name
    LEFT JOIN exact_mixed AS exact
        ON exact.table_name = expected.table_name
       AND exact.policy_name = expected.policy_name
)
SELECT
    actual_policy_name IS NOT NULL AS object_present,
    table_name,
    policy_name,
    expected_role,
    actual_role,
    expected_command,
    actual_command,
    expected_mode,
    actual_mode,
    using_expression,
    COALESCE(predicate_check_passed, false) AS predicate_check_passed,
    actual_policy_name IS NOT NULL
        AND actual_role = expected_role
        AND actual_command = expected_command
        AND actual_mode = expected_mode
        AND COALESCE(predicate_check_passed, false) AS check_passed,
    CASE
        WHEN actual_policy_name IS NULL THEN 'missing_catalog_read_policy'
        WHEN actual_role IS DISTINCT FROM expected_role
        THEN 'catalog_read_role_mismatch'
        WHEN actual_command IS DISTINCT FROM expected_command
        THEN 'catalog_read_command_mismatch'
        WHEN actual_mode IS DISTINCT FROM expected_mode
        THEN 'catalog_read_mode_mismatch'
        WHEN NOT COALESCE(predicate_check_passed, false)
        THEN 'catalog_read_predicate_mismatch'
        ELSE 'ok'
    END AS finding_code
FROM comparison
ORDER BY table_name, policy_name;


-- 06. Every child write operation has an expected restrictive approved-owner
-- guard and a separate applicable permissive seller policy. Restrictive policies
-- constrain access; they do not independently grant seller or admin access.
WITH expected_policies(
    table_name,
    policy_name,
    expected_role,
    expected_command,
    expected_mode
) AS (
    VALUES
        ('product_color'::name, 'phase32b_product_color_insert_guard'::name, 'authenticated'::text, 'INSERT'::text, 'RESTRICTIVE'::text),
        ('product_color'::name, 'phase32b_product_color_update_guard'::name, 'authenticated'::text, 'UPDATE'::text, 'RESTRICTIVE'::text),
        ('product_color'::name, 'phase32b_product_color_delete_guard'::name, 'authenticated'::text, 'DELETE'::text, 'RESTRICTIVE'::text),
        ('product_image'::name, 'phase32b_product_image_insert_guard'::name, 'authenticated'::text, 'INSERT'::text, 'RESTRICTIVE'::text),
        ('product_image'::name, 'phase32b_product_image_update_guard'::name, 'authenticated'::text, 'UPDATE'::text, 'RESTRICTIVE'::text),
        ('product_image'::name, 'phase32b_product_image_delete_guard'::name, 'authenticated'::text, 'DELETE'::text, 'RESTRICTIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_insert_guard'::name, 'authenticated'::text, 'INSERT'::text, 'RESTRICTIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_update_guard'::name, 'authenticated'::text, 'UPDATE'::text, 'RESTRICTIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_delete_guard'::name, 'authenticated'::text, 'DELETE'::text, 'RESTRICTIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_insert_guard'::name, 'authenticated'::text, 'INSERT'::text, 'RESTRICTIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_update_guard'::name, 'authenticated'::text, 'UPDATE'::text, 'RESTRICTIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_delete_guard'::name, 'authenticated'::text, 'DELETE'::text, 'RESTRICTIVE'::text)
),
comparison AS (
    SELECT
        expected.*,
        guard.policyname AS actual_policy_name,
        array_to_string(guard.roles, ', ') AS actual_role,
        guard.cmd AS actual_command,
        guard.permissive AS actual_mode,
        guard.qual AS using_expression,
        guard.with_check AS with_check_expression,
        lower(concat_ws(' ', guard.qual, guard.with_check))
            ~ 'current_party_is_approved' AS requires_approved_party,
        lower(concat_ws(' ', guard.qual, guard.with_check))
            ~ 'current_marketplace_party_id' AS requires_ownership,
        lower(concat_ws(' ', guard.qual, guard.with_check))
            !~ 'is_admin' AS has_no_admin_grant_claim,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS seller
            WHERE seller.schemaname = 'public'
              AND seller.tablename = expected.table_name
              AND seller.policyname <> expected.policy_name
              AND seller.permissive = 'PERMISSIVE'
              AND seller.roles && ARRAY['public', 'authenticated']::name[]
              AND seller.cmd IN ('ALL', expected.expected_command)
              AND lower(concat_ws(' ', seller.qual, seller.with_check))
                  ~ 'current_marketplace_party_id'
        ) AS permissive_seller_policy_present
    FROM expected_policies AS expected
    LEFT JOIN pg_catalog.pg_policies AS guard
        ON guard.schemaname = 'public'
       AND guard.tablename = expected.table_name
       AND guard.policyname = expected.policy_name
)
SELECT
    actual_policy_name IS NOT NULL AS object_present,
    table_name,
    policy_name,
    expected_role,
    actual_role,
    expected_command,
    actual_command,
    expected_mode,
    actual_mode,
    using_expression,
    with_check_expression,
    COALESCE(requires_approved_party, false) AS requires_approved_party,
    COALESCE(requires_ownership, false) AS requires_ownership,
    COALESCE(has_no_admin_grant_claim, false) AS has_no_admin_grant_claim,
    permissive_seller_policy_present,
    actual_policy_name IS NOT NULL
        AND actual_role = expected_role
        AND actual_command = expected_command
        AND actual_mode = expected_mode
        AND COALESCE(requires_approved_party, false)
        AND COALESCE(requires_ownership, false)
        AND COALESCE(has_no_admin_grant_claim, false)
        AND permissive_seller_policy_present AS check_passed,
    CASE
        WHEN actual_policy_name IS NULL THEN 'missing_child_write_guard'
        WHEN actual_role IS DISTINCT FROM expected_role
        THEN 'child_write_guard_role_mismatch'
        WHEN actual_command IS DISTINCT FROM expected_command
        THEN 'child_write_guard_command_mismatch'
        WHEN actual_mode IS DISTINCT FROM expected_mode
        THEN 'child_write_guard_mode_mismatch'
        WHEN NOT COALESCE(requires_approved_party, false)
          OR NOT COALESCE(requires_ownership, false)
          OR NOT COALESCE(has_no_admin_grant_claim, false)
        THEN 'child_write_guard_predicate_mismatch'
        WHEN NOT permissive_seller_policy_present
        THEN 'missing_permissive_seller_write_policy'
        ELSE 'ok'
    END AS finding_code
FROM comparison
ORDER BY table_name, expected_command;


-- 07. Hardened helper signatures, ownership, behavior, search path, and grants.
WITH expected_functions(function_name, result_type, source_text) AS (
    VALUES
        (
            'is_admin'::name,
            'boolean'::regtype,
            $source$SELECT EXISTS (
                SELECT 1
                FROM public.admin_user AS admin_row
                WHERE admin_row.user_id = auth.uid()
                  AND admin_row.is_active
            );$source$::text
        ),
        (
            'current_marketplace_party_id'::name,
            'uuid'::regtype,
            $source$SELECT party.id
                FROM public.marketplace_party AS party
                WHERE party.user_id = auth.uid();$source$::text
        ),
        (
            'current_party_is_approved'::name,
            'boolean'::regtype,
            $source$SELECT EXISTS (
                SELECT 1
                FROM public.marketplace_party AS party
                WHERE party.user_id = auth.uid()
                  AND party.approval_state =
                      'approved'::public.party_approval_state
            );$source$::text
        )
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
    language_row.lanname AS language_name,
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
                pg_catalog.acldefault(
                    'f'::pg_catalog."char",
                    function_row.proowner
                )
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
    btrim(
        pg_catalog.regexp_replace(
            lower(function_row.prosrc), '[[:space:]]', '', 'g'
        ),
        ';'
    ) = btrim(
        pg_catalog.regexp_replace(
            lower(expected.source_text), '[[:space:]]', '', 'g'
        ),
        ';'
    ) AS complete_definition_matches,
    pg_catalog.pg_get_userbyid(function_row.proowner) = 'postgres'
    AND function_row.pronargs = 0
    AND function_row.prorettype = expected.result_type
    AND language_row.lanname = 'sql'
    AND function_row.prosecdef
    AND function_row.provolatile = 's'
    AND btrim(
        pg_catalog.regexp_replace(
            lower(function_row.prosrc), '[[:space:]]', '', 'g'
        ),
        ';'
    ) = btrim(
        pg_catalog.regexp_replace(
            lower(expected.source_text), '[[:space:]]', '', 'g'
        ),
        ';'
    )
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
                pg_catalog.acldefault(
                    'f'::pg_catalog."char",
                    function_row.proowner
                )
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
LEFT JOIN pg_catalog.pg_language AS language_row
    ON language_row.oid = function_row.prolang
CROSS JOIN roles
ORDER BY expected.function_name, identity_arguments;


-- 08. No anon-facing policy may reference a helper denied to anon. This emits
-- one visible status row; unexpected policy names are metadata only.
WITH anon_role AS (
    SELECT oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon'
),
violations AS (
    SELECT
        relation.relname AS table_name,
        policy.polname AS policy_name
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    CROSS JOIN anon_role AS role_row
    WHERE namespace.nspname = 'public'
      AND (
          0 = ANY(policy.polroles)
          OR role_row.oid = ANY(policy.polroles)
      )
      AND lower(concat_ws(
          ' ',
          pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
          pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true)
      )) ~ 'current_marketplace_party_id|current_party_is_approved|is_admin'
)
SELECT
    true AS object_present,
    0::bigint AS expected_violation_count,
    count(*) AS actual_violation_count,
    string_agg(
        format('public.%I.%I', table_name, policy_name),
        ', ' ORDER BY table_name, policy_name
    ) AS violating_policies,
    count(*) = 0 AS check_passed,
    CASE WHEN count(*) = 0 THEN 'ok' ELSE 'anon_helper_dependency' END
        AS finding_code
FROM violations;


-- 09. Dangerous existing grants. A safe result is empty.
WITH expected_roles(role_name) AS (
    VALUES ('PUBLIC'::name), ('anon'::name), ('authenticated'::name)
),
target_roles AS (
    SELECT expected.role_name AS rolname, role_row.oid
    FROM expected_roles AS expected
    LEFT JOIN pg_catalog.pg_roles AS role_row
        ON role_row.rolname = expected.role_name
       AND expected.role_name <> 'PUBLIC'
),
dangerous_privileges(role_name, privilege_name) AS (
    VALUES
        ('PUBLIC'::name, 'INSERT'::text),
        ('PUBLIC'::name, 'UPDATE'::text),
        ('PUBLIC'::name, 'DELETE'::text),
        ('PUBLIC'::name, 'TRUNCATE'::text),
        ('PUBLIC'::name, 'REFERENCES'::text),
        ('PUBLIC'::name, 'TRIGGER'::text),
        ('PUBLIC'::name, 'MAINTAIN'::text),
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
    SELECT relation.oid, relation.relname, relation.relacl, relation.relowner
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
WHERE CASE
    WHEN privilege.privilege_name = 'MAINTAIN'
     AND current_setting('server_version_num')::integer < 170000
    THEN false
    WHEN role_row.rolname = 'PUBLIC'
    THEN EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(
                table_row.relacl,
                pg_catalog.acldefault(
                    'r'::pg_catalog."char",
                    table_row.relowner
                )
            )
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = privilege.privilege_name
    )
    ELSE pg_catalog.has_table_privilege(
        role_row.oid,
        table_row.oid,
        privilege.privilege_name
    )
END
ORDER BY table_row.relname, role_row.rolname, privilege.privilege_name;


-- 10. Exact inventory and anonymous SELECT allowlist. All 34 rows must pass.
WITH expected_tables(table_name, anon_select_expected) AS (
    VALUES
        ('address'::name, false),
        ('admin_user'::name, false),
        ('cart'::name, false),
        ('cart_line'::name, false),
        ('category'::name, true),
        ('commission'::name, false),
        ('commission_reversal'::name, false),
        ('custom_offering'::name, true),
        ('customer_profile'::name, false),
        ('design'::name, false),
        ('design_product_reference'::name, false),
        ('design_version'::name, false),
        ('furnishing_request'::name, false),
        ('furnishing_request_design_version'::name, false),
        ('marketplace_party'::name, true),
        ('offer'::name, false),
        ('offer_line_item'::name, false),
        ('order_line_item'::name, false),
        ('party_capability'::name, true),
        ('payment'::name, false),
        ('platform_config'::name, false),
        ('product'::name, true),
        ('product_3d_model'::name, true),
        ('product_color'::name, true),
        ('product_enrichment_assignment'::name, true),
        ('product_enrichment_attribute'::name, true),
        ('product_image'::name, true),
        ('purchase_order'::name, false),
        ('refund'::name, false),
        ('review'::name, true),
        ('saved_space'::name, false),
        ('service_request'::name, false),
        ('service_type'::name, true),
        ('settlement'::name, false)
),
actual_tables AS (
    SELECT relation.oid, relation.relname
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
),
anon_role AS (
    SELECT oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon'
),
comparison AS (
    SELECT
        expected.table_name,
        expected.anon_select_expected,
        actual.oid IS NOT NULL AS table_exists,
        CASE
            WHEN actual.oid IS NULL THEN NULL
            ELSE pg_catalog.has_table_privilege(
                role_row.oid,
                actual.oid,
                'SELECT'
            )
        END AS anon_select_actual
    FROM expected_tables AS expected
    LEFT JOIN actual_tables AS actual
        ON actual.relname = expected.table_name
    CROSS JOIN anon_role AS role_row
)
SELECT
    comparison.table_name,
    comparison.anon_select_expected,
    comparison.table_exists,
    comparison.anon_select_actual,
    comparison.table_exists
        AND comparison.anon_select_actual = comparison.anon_select_expected
        AS check_passed,
    CASE
        WHEN NOT comparison.table_exists THEN 'missing_expected_table'
        WHEN comparison.anon_select_actual IS DISTINCT FROM
            comparison.anon_select_expected
        THEN 'anon_select_mismatch'
        ELSE NULL
    END AS finding
FROM comparison
UNION ALL
SELECT
    actual.relname,
    NULL::boolean,
    true,
    pg_catalog.has_table_privilege(role_row.oid, actual.oid, 'SELECT'),
    false,
    'unexpected_public_table'
FROM actual_tables AS actual
CROSS JOIN anon_role AS role_row
WHERE NOT EXISTS (
    SELECT 1
    FROM expected_tables AS expected
    WHERE expected.table_name = actual.relname
)
ORDER BY table_name;


-- 11. Effective postgres defaults across four scopes. A safe REVOKE may remove
-- a pg_default_acl row, so row presence is not a success condition. For public
-- objects, schema-local defaults are added to the global/hard-wired defaults.
WITH expected_scopes(
    scope_name,
    schema_name,
    object_type,
    object_type_code,
    expected_role,
    expected_command
) AS (
    VALUES
        ('public_tables'::text, 'public'::name, 'table'::text, 'r'::pg_catalog."char", 'PUBLIC, anon, authenticated'::text, 'NO EFFECTIVE CLIENT DEFAULT PRIVILEGES'::text),
        ('public_sequences'::text, 'public'::name, 'sequence'::text, 'S'::pg_catalog."char", 'PUBLIC, anon, authenticated'::text, 'NO EFFECTIVE CLIENT DEFAULT PRIVILEGES'::text),
        ('public_functions'::text, 'public'::name, 'function'::text, 'f'::pg_catalog."char", 'PUBLIC, anon, authenticated'::text, 'NO EFFECTIVE CLIENT DEFAULT EXECUTE'::text),
        ('global_functions'::text, NULL::name, 'function'::text, 'f'::pg_catalog."char", 'PUBLIC, anon, authenticated'::text, 'NO EFFECTIVE CLIENT DEFAULT EXECUTE'::text)
),
owner_role AS (
    SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname = 'postgres'
),
comparison AS (
    SELECT
        expected.*,
        owner.oid AS owner_oid,
        namespace.oid AS namespace_oid,
        (
            SELECT string_agg(
                format(
                    '%s:%s',
                    CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
                    acl.privilege_type
                ),
                ', ' ORDER BY
                CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
                acl.privilege_type
            )
            FROM pg_catalog.aclexplode(
                COALESCE(
                    global_defaults.defaclacl,
                    pg_catalog.acldefault(expected.object_type_code, owner.oid)
                ) || CASE
                    WHEN expected.schema_name IS NULL
                    THEN ARRAY[]::aclitem[]
                    ELSE COALESCE(
                        schema_defaults.defaclacl,
                        ARRAY[]::aclitem[]
                    )
                END
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
            WHERE COALESCE(grantee.rolname, 'PUBLIC')
                IN ('PUBLIC', 'anon', 'authenticated')
              AND (
                  expected.object_type_code IN (
                      'r'::pg_catalog."char",
                      'S'::pg_catalog."char"
                  )
                  OR acl.privilege_type = 'EXECUTE'
              )
        ) AS actual_client_defaults
    FROM expected_scopes AS expected
    LEFT JOIN owner_role AS owner ON true
    LEFT JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.nspname = expected.schema_name
    LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
        ON global_defaults.defaclrole = owner.oid
       AND global_defaults.defaclobjtype = expected.object_type_code
       AND global_defaults.defaclnamespace = 0
    LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
        ON schema_defaults.defaclrole = owner.oid
       AND schema_defaults.defaclobjtype = expected.object_type_code
       AND schema_defaults.defaclnamespace = namespace.oid
       AND expected.schema_name IS NOT NULL
)
SELECT
    owner_oid IS NOT NULL
        AND (schema_name IS NULL OR namespace_oid IS NOT NULL) AS object_present,
    'postgres'::name AS owner_name,
    COALESCE(schema_name, '<all_schemas>'::name) AS schema_scope,
    scope_name,
    object_type,
    expected_role,
    actual_client_defaults AS actual_role,
    expected_command,
    CASE WHEN actual_client_defaults IS NULL THEN expected_command
        ELSE 'EFFECTIVE CLIENT DEFAULT PRIVILEGES PRESENT'
    END AS actual_command,
    owner_oid IS NOT NULL
        AND (schema_name IS NULL OR namespace_oid IS NOT NULL)
        AND actual_client_defaults IS NULL AS check_passed,
    CASE
        WHEN owner_oid IS NULL THEN 'missing_postgres_role'
        WHEN schema_name IS NOT NULL AND namespace_oid IS NULL
        THEN 'missing_expected_schema'
        WHEN actual_client_defaults IS NOT NULL
        THEN 'unsafe_effective_postgres_default_privilege'
        ELSE 'ok'
    END AS finding_code
FROM comparison
ORDER BY scope_name;


-- 12. Every reviewed RLS-enabled table must still have at least one policy. A
-- VALUES/LEFT JOIN comparison makes missing tables and missing policies visible.
WITH expected_tables(table_name) AS (
    VALUES
        ('address'::name), ('admin_user'::name), ('cart'::name),
        ('cart_line'::name), ('category'::name), ('commission'::name),
        ('commission_reversal'::name), ('custom_offering'::name),
        ('customer_profile'::name), ('design'::name),
        ('design_product_reference'::name), ('design_version'::name),
        ('furnishing_request'::name),
        ('furnishing_request_design_version'::name),
        ('marketplace_party'::name), ('offer'::name),
        ('offer_line_item'::name), ('order_line_item'::name),
        ('party_capability'::name), ('payment'::name),
        ('platform_config'::name), ('product'::name),
        ('product_3d_model'::name), ('product_color'::name),
        ('product_enrichment_assignment'::name),
        ('product_enrichment_attribute'::name), ('product_image'::name),
        ('purchase_order'::name), ('refund'::name), ('review'::name),
        ('saved_space'::name), ('service_request'::name),
        ('service_type'::name), ('settlement'::name)
),
actual_tables AS (
    SELECT relation.oid, relation.relname, relation.relrowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
),
comparison AS (
    SELECT
        expected.table_name,
        actual.oid AS table_oid,
        actual.relrowsecurity,
        count(policy.oid) AS policy_count
    FROM expected_tables AS expected
    LEFT JOIN actual_tables AS actual ON actual.relname = expected.table_name
    LEFT JOIN pg_catalog.pg_policy AS policy ON policy.polrelid = actual.oid
    GROUP BY expected.table_name, actual.oid, actual.relrowsecurity
)
SELECT
    table_oid IS NOT NULL AS object_present,
    table_name,
    relrowsecurity AS rls_enabled,
    policy_count,
    table_oid IS NOT NULL
        AND relrowsecurity
        AND policy_count > 0 AS check_passed,
    CASE
        WHEN table_oid IS NULL THEN 'missing_expected_table'
        WHEN NOT relrowsecurity THEN 'rls_disabled'
        WHEN policy_count = 0 THEN 'rls_table_without_policy'
        ELSE 'ok'
    END AS finding_code
FROM comparison
ORDER BY table_name;


-- 13. Final verification summary. One row is returned for every numbered
-- section above, including sections whose detailed query reports no violations.
WITH expected_tables(table_name, anon_select_expected) AS (
    VALUES
        ('address'::name, false), ('admin_user'::name, false),
        ('cart'::name, false), ('cart_line'::name, false),
        ('category'::name, true), ('commission'::name, false),
        ('commission_reversal'::name, false), ('custom_offering'::name, true),
        ('customer_profile'::name, false), ('design'::name, false),
        ('design_product_reference'::name, false), ('design_version'::name, false),
        ('furnishing_request'::name, false),
        ('furnishing_request_design_version'::name, false),
        ('marketplace_party'::name, true), ('offer'::name, false),
        ('offer_line_item'::name, false), ('order_line_item'::name, false),
        ('party_capability'::name, true), ('payment'::name, false),
        ('platform_config'::name, false), ('product'::name, true),
        ('product_3d_model'::name, true), ('product_color'::name, true),
        ('product_enrichment_assignment'::name, true),
        ('product_enrichment_attribute'::name, true),
        ('product_image'::name, true), ('purchase_order'::name, false),
        ('refund'::name, false), ('review'::name, true),
        ('saved_space'::name, false), ('service_request'::name, false),
        ('service_type'::name, true), ('settlement'::name, false)
),
actual_tables AS (
    SELECT
        relation.oid,
        relation.relname,
        relation.relrowsecurity,
        relation.relacl,
        relation.relowner
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
),
resolved_roles AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'authenticated')
            AS authenticated_oid,
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'service_role')
            AS service_role_oid
),
section_01_checks AS (
    SELECT
        actual.oid IS NOT NULL AS object_present,
        actual.oid IS NOT NULL AND actual.relrowsecurity AS check_passed
    FROM expected_tables AS expected
    LEFT JOIN actual_tables AS actual ON actual.relname = expected.table_name
    UNION ALL
    SELECT true, false
    FROM actual_tables AS actual
    WHERE NOT EXISTS (
        SELECT 1 FROM expected_tables AS expected
        WHERE expected.table_name = actual.relname
    )
),
mp_columns(column_name, insert_expected, update_expected) AS (
    VALUES
        ('id'::name, false, false), ('user_id'::name, true, false),
        ('business_name'::name, true, true),
        ('business_description'::name, true, true),
        ('logo_url'::name, true, true), ('coverage_area'::name, true, true),
        ('approval_state'::name, false, false),
        ('state_reason'::name, false, false)
),
mp_roles(role_name, role_oid, table_insert_expected, table_update_expected) AS (
    SELECT 'anon'::name, roles.anon_oid, false, false FROM resolved_roles AS roles
    UNION ALL
    SELECT 'authenticated'::name, roles.authenticated_oid, false, false
    FROM resolved_roles AS roles
    UNION ALL
    SELECT 'service_role'::name, roles.service_role_oid, true, true
    FROM resolved_roles AS roles
),
section_02_checks AS (
    SELECT
        role_row.role_oid IS NOT NULL AND party.oid IS NOT NULL AS object_present,
        role_row.role_oid IS NOT NULL
        AND party.oid IS NOT NULL
        AND pg_catalog.has_table_privilege(
            role_row.role_oid,
            party.oid,
            'INSERT'
        ) = role_row.table_insert_expected
        AND pg_catalog.has_table_privilege(
            role_row.role_oid,
            party.oid,
            'UPDATE'
        ) = role_row.table_update_expected
        AND pg_catalog.has_column_privilege(
            role_row.role_oid,
            party.oid,
            column_row.column_name,
            'INSERT'
        ) = CASE role_row.role_name
            WHEN 'authenticated' THEN column_row.insert_expected
            WHEN 'service_role' THEN true
            ELSE false
        END
        AND pg_catalog.has_column_privilege(
            role_row.role_oid,
            party.oid,
            column_row.column_name,
            'UPDATE'
        ) = CASE role_row.role_name
            WHEN 'authenticated' THEN column_row.update_expected
            WHEN 'service_role' THEN true
            ELSE false
        END AS check_passed
    FROM mp_roles AS role_row
    CROSS JOIN mp_columns AS column_row
    LEFT JOIN actual_tables AS party ON party.relname = 'marketplace_party'
),
section_03_actual AS (
    SELECT
        count(*) AS policy_count,
        min(policy.permissive) AS permissive,
        min(policy.roles::text) AS roles,
        min(policy.qual) AS qual,
        min(policy.with_check) AS with_check
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename = 'marketplace_party'
      AND policy.cmd = 'INSERT'
),
section_03_checks AS (
    SELECT
        policy_count = 1 AS object_present,
        policy_count AS actual_weight,
        policy_count = 1
        AND permissive = 'PERMISSIVE'
        AND roles = '{authenticated}'
        AND qual IS NULL
        AND with_check ~* 'user_id.*auth\.uid'
        AND with_check ~* 'approval_state.*pending'
        AND with_check ~* 'state_reason.*IS NULL' AS check_passed
    FROM section_03_actual
),
section_04_checks AS (
    SELECT
        view_row.oid IS NOT NULL AS object_present,
        view_row.oid IS NOT NULL
        AND pg_catalog.pg_get_userbyid(view_row.relowner) = 'postgres'
        AND COALESCE(
            view_row.reloptions @> ARRAY['security_invoker=true'],
            false
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    view_row.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        view_row.relowner
                    )
                )
            ) AS acl
            WHERE acl.grantee = 0 AND acl.privilege_type = 'SELECT'
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
    FROM resolved_roles AS roles
    LEFT JOIN pg_catalog.pg_class AS view_row
        ON view_row.oid = (
            SELECT relation.oid
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'order_financial_position'
              AND relation.relkind = 'v'
        )
),
read_expected(table_name, policy_name, role_name, policy_mode, predicate_kind) AS (
    VALUES
        ('category'::name, 'phase32b_category_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'active'::text),
        ('category'::name, 'phase32b_category_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'active_admin'::text),
        ('custom_offering'::name, 'custom_offering_select_published_or_own'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'custom_mixed'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'custom_public'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'custom_public'::text),
        ('product'::name, 'product_select_published_or_own'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product'::name, 'phase32b_product_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product'::name, 'phase32b_product_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'product_public'::text),
        ('product'::name, 'phase32b_product_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'product_public'::text),
        ('product'::name, 'phase32b_product_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'product_authenticated'::text),
        ('product_color'::name, 'product_color_select'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_color'::name, 'phase32b_product_color_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_color'::name, 'phase32b_product_color_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'product_image_select'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_image'::name, 'phase32b_product_image_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_image'::name, 'phase32b_product_image_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'product_3d_model_select'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'child_parent'::text),
        ('product_enrichment_assignment'::name, 'product_enrichment_assignment_select'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'mixed_owner'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text, 'owner'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text, 'enrichment_public'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text, 'enrichment_public'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text, 'enrichment_authenticated'::text)
),
summary_exact_mixed(table_name, policy_name, expected_using_expression) AS (
    VALUES
        ('custom_offering'::name, 'custom_offering_select_published_or_own'::name, $predicate$(publication_state = 'published'::public.custom_offering_state) OR (marketplace_party_id = public.current_marketplace_party_id()) OR public.is_admin()$predicate$::text),
        ('product'::name, 'product_select_published_or_own'::name, $predicate$(lifecycle_state = 'published'::public.product_lifecycle_state) OR (marketplace_party_id = public.current_marketplace_party_id()) OR public.is_admin()$predicate$::text),
        ('product_color'::name, 'product_color_select'::name, $predicate$EXISTS (SELECT 1 FROM public.product AS parent_product WHERE parent_product.id = product_color.product_id AND (parent_product.lifecycle_state = 'published'::public.product_lifecycle_state OR parent_product.marketplace_party_id = public.current_marketplace_party_id() OR public.is_admin()))$predicate$::text),
        ('product_image'::name, 'product_image_select'::name, $predicate$EXISTS (SELECT 1 FROM public.product AS parent_product WHERE parent_product.id = product_image.product_id AND (parent_product.lifecycle_state = 'published'::public.product_lifecycle_state OR parent_product.marketplace_party_id = public.current_marketplace_party_id() OR public.is_admin()))$predicate$::text),
        ('product_3d_model'::name, 'product_3d_model_select'::name, $predicate$EXISTS (SELECT 1 FROM public.product AS parent_product WHERE parent_product.id = product_3d_model.product_id AND (parent_product.lifecycle_state = 'published'::public.product_lifecycle_state OR parent_product.marketplace_party_id = public.current_marketplace_party_id() OR public.is_admin()))$predicate$::text),
        ('product_enrichment_assignment'::name, 'product_enrichment_assignment_select'::name, $predicate$EXISTS (SELECT 1 FROM public.product AS parent_product WHERE parent_product.id = product_enrichment_assignment.product_id AND (parent_product.lifecycle_state = 'published'::public.product_lifecycle_state OR parent_product.marketplace_party_id = public.current_marketplace_party_id() OR public.is_admin()))$predicate$::text)
),
section_05_checks AS (
    SELECT
        policy.policyname IS NOT NULL AS object_present,
        policy.policyname IS NOT NULL
        AND array_to_string(policy.roles, ', ') = expected.role_name
        AND policy.cmd = 'SELECT'
        AND policy.permissive = expected.policy_mode
        AND CASE expected.predicate_kind
            WHEN 'active' THEN policy.qual ~* 'is_active.*true'
                AND lower(policy.qual) !~ 'is_admin|current_marketplace_party_id'
            WHEN 'active_admin' THEN policy.qual ~* 'is_active.*true'
                AND policy.qual ~* 'is_admin'
            WHEN 'custom_mixed' THEN
                pg_catalog.regexp_replace(
                    lower(policy.qual), '[[:space:]]', '', 'g'
                ) = pg_catalog.regexp_replace(
                    lower(exact.expected_using_expression),
                    '[[:space:]]',
                    '',
                    'g'
                )
            WHEN 'custom_public' THEN policy.qual ~* 'publication_state.*published'
                AND policy.qual ~* 'custom_offering_state'
                AND lower(policy.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'mixed_owner' THEN
                pg_catalog.regexp_replace(
                    lower(policy.qual), '[[:space:]]', '', 'g'
                ) = pg_catalog.regexp_replace(
                    lower(exact.expected_using_expression),
                    '[[:space:]]',
                    '',
                    'g'
                )
            WHEN 'owner' THEN
                lower(policy.qual) ~ 'current_marketplace_party_id|is_admin'
            WHEN 'product_public' THEN
                policy.qual ~* 'lifecycle_state.*published'
                AND policy.qual ~* 'approval_state.*approved'
                AND policy.qual ~* 'is_active.*true'
                AND lower(policy.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'product_authenticated' THEN
                policy.qual ~* 'lifecycle_state.*published'
                AND policy.qual ~* 'approval_state.*approved'
                AND policy.qual ~* 'is_active.*true'
                AND lower(policy.qual) ~ 'current_marketplace_party_id|is_admin'
            WHEN 'child_parent' THEN
                policy.qual ~* 'from[[:space:]]+(public\.)?product'
            WHEN 'enrichment_public' THEN
                policy.qual ~* 'confirmation_state.*party_confirmed'
                AND policy.qual ~* 'from[[:space:]]+(public\.)?product'
                AND lower(policy.qual) !~
                    'current_marketplace_party_id|current_party_is_approved|is_admin'
            WHEN 'enrichment_authenticated' THEN
                policy.qual ~* 'confirmation_state.*party_confirmed'
                AND lower(policy.qual) ~ 'current_marketplace_party_id|is_admin'
            ELSE false
        END AS check_passed
    FROM read_expected AS expected
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = expected.table_name
       AND policy.policyname = expected.policy_name
    LEFT JOIN summary_exact_mixed AS exact
        ON exact.table_name = expected.table_name
       AND exact.policy_name = expected.policy_name
),
write_expected(table_name, policy_name, command_name) AS (
    VALUES
        ('product_color'::name, 'phase32b_product_color_insert_guard'::name, 'INSERT'::text),
        ('product_color'::name, 'phase32b_product_color_update_guard'::name, 'UPDATE'::text),
        ('product_color'::name, 'phase32b_product_color_delete_guard'::name, 'DELETE'::text),
        ('product_image'::name, 'phase32b_product_image_insert_guard'::name, 'INSERT'::text),
        ('product_image'::name, 'phase32b_product_image_update_guard'::name, 'UPDATE'::text),
        ('product_image'::name, 'phase32b_product_image_delete_guard'::name, 'DELETE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_insert_guard'::name, 'INSERT'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_update_guard'::name, 'UPDATE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_delete_guard'::name, 'DELETE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_insert_guard'::name, 'INSERT'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_update_guard'::name, 'UPDATE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_delete_guard'::name, 'DELETE'::text)
),
section_06_checks AS (
    SELECT
        guard.policyname IS NOT NULL AS object_present,
        guard.policyname IS NOT NULL
        AND guard.roles = ARRAY['authenticated']::name[]
        AND guard.cmd = expected.command_name
        AND guard.permissive = 'RESTRICTIVE'
        AND lower(concat_ws(' ', guard.qual, guard.with_check))
            ~ 'current_party_is_approved'
        AND lower(concat_ws(' ', guard.qual, guard.with_check))
            ~ 'current_marketplace_party_id'
        AND lower(concat_ws(' ', guard.qual, guard.with_check)) !~ 'is_admin'
        AND EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS seller
            WHERE seller.schemaname = 'public'
              AND seller.tablename = expected.table_name
              AND seller.policyname <> expected.policy_name
              AND seller.permissive = 'PERMISSIVE'
              AND seller.roles && ARRAY['public', 'authenticated']::name[]
              AND seller.cmd IN ('ALL', expected.command_name)
              AND lower(concat_ws(' ', seller.qual, seller.with_check))
                  ~ 'current_marketplace_party_id'
        ) AS check_passed
    FROM write_expected AS expected
    LEFT JOIN pg_catalog.pg_policies AS guard
        ON guard.schemaname = 'public'
       AND guard.tablename = expected.table_name
       AND guard.policyname = expected.policy_name
),
helper_expected(function_name, return_type, source_text) AS (
    VALUES
        (
            'is_admin'::name,
            'boolean'::regtype,
            $source$SELECT EXISTS (
                SELECT 1
                FROM public.admin_user AS admin_row
                WHERE admin_row.user_id = auth.uid()
                  AND admin_row.is_active
            );$source$::text
        ),
        (
            'current_marketplace_party_id'::name,
            'uuid'::regtype,
            $source$SELECT party.id
                FROM public.marketplace_party AS party
                WHERE party.user_id = auth.uid();$source$::text
        ),
        (
            'current_party_is_approved'::name,
            'boolean'::regtype,
            $source$SELECT EXISTS (
                SELECT 1
                FROM public.marketplace_party AS party
                WHERE party.user_id = auth.uid()
                  AND party.approval_state =
                      'approved'::public.party_approval_state
            );$source$::text
        )
),
section_07_checks AS (
    SELECT
        function_row.oid IS NOT NULL AS object_present,
        function_row.oid IS NOT NULL
        AND function_row.pronargs = 0
        AND function_row.prorettype = expected.return_type
        AND function_row.provolatile = 's'
        AND function_row.prosecdef
        AND language_row.lanname = 'sql'
        AND pg_catalog.pg_get_userbyid(function_row.proowner) = 'postgres'
        AND btrim(
            pg_catalog.regexp_replace(
                lower(function_row.prosrc), '[[:space:]]', '', 'g'
            ),
            ';'
        ) = btrim(
            pg_catalog.regexp_replace(
                lower(expected.source_text), '[[:space:]]', '', 'g'
            ),
            ';'
        )
        AND EXISTS (
            SELECT 1 FROM unnest(function_row.proconfig) AS setting
            WHERE pg_catalog.regexp_replace(
                setting,
                '^search_path=',
                ''
            ) IN ('', '""')
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
        ) AS check_passed
    FROM helper_expected AS expected
    LEFT JOIN pg_catalog.pg_proc AS function_row
        ON function_row.pronamespace = 'public'::regnamespace
       AND function_row.proname = expected.function_name
    LEFT JOIN pg_catalog.pg_language AS language_row
        ON language_row.oid = function_row.prolang
    CROSS JOIN resolved_roles AS roles
),
section_08_checks AS (
    SELECT
        true AS object_present,
        NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
            CROSS JOIN resolved_roles AS roles
            WHERE relation.relnamespace = 'public'::regnamespace
              AND (0 = ANY(policy.polroles) OR roles.anon_oid = ANY(policy.polroles))
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
                  pg_catalog.pg_get_expr(
                      policy.polwithcheck,
                      policy.polrelid,
                      true
                  )
              )) ~ 'current_marketplace_party_id|current_party_is_approved|is_admin'
        ) AS check_passed
),
section_09_checks AS (
    SELECT
        true AS object_present,
        NOT EXISTS (
            SELECT 1
            FROM actual_tables AS table_row
            CROSS JOIN resolved_roles AS roles
            WHERE EXISTS (
                SELECT 1
                FROM pg_catalog.aclexplode(
                    COALESCE(
                        table_row.relacl,
                        pg_catalog.acldefault(
                            'r'::pg_catalog."char",
                            table_row.relowner
                        )
                    )
                ) AS acl
                WHERE acl.grantee = 0
                  AND acl.privilege_type IN (
                      'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
                      'REFERENCES', 'TRIGGER', 'MAINTAIN'
                  )
            )
            OR pg_catalog.has_table_privilege(
                roles.anon_oid,
                table_row.oid,
                'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
            )
            OR pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                table_row.oid,
                'TRUNCATE, REFERENCES, TRIGGER'
            )
            OR CASE
                WHEN current_setting('server_version_num')::integer >= 170000
                THEN pg_catalog.has_table_privilege(
                    roles.anon_oid,
                    table_row.oid,
                    'MAINTAIN'
                ) OR pg_catalog.has_table_privilege(
                    roles.authenticated_oid,
                    table_row.oid,
                    'MAINTAIN'
                )
                ELSE false
            END
        ) AS check_passed
),
section_10_checks AS (
    SELECT
        actual.oid IS NOT NULL AS object_present,
        actual.oid IS NOT NULL
        AND pg_catalog.has_table_privilege(
            roles.anon_oid,
            actual.oid,
            'SELECT'
        ) = expected.anon_select_expected AS check_passed
    FROM expected_tables AS expected
    LEFT JOIN actual_tables AS actual ON actual.relname = expected.table_name
    CROSS JOIN resolved_roles AS roles
    UNION ALL
    SELECT true, false
    FROM actual_tables AS actual
    WHERE NOT EXISTS (
        SELECT 1 FROM expected_tables AS expected
        WHERE expected.table_name = actual.relname
    )
),
default_expected(scope_name, schema_scope, object_type) AS (
    VALUES
        ('public_tables'::text, 'public'::name, 'r'::pg_catalog."char"),
        ('public_sequences'::text, 'public'::name, 'S'::pg_catalog."char"),
        ('public_functions'::text, 'public'::name, 'f'::pg_catalog."char"),
        ('global_functions'::text, NULL::name, 'f'::pg_catalog."char")
),
postgres_role AS (
    SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'postgres'
),
section_11_checks AS (
    SELECT
        owner.oid IS NOT NULL
            AND (
                expected.schema_scope IS NULL
                OR namespace.oid IS NOT NULL
            ) AS object_present,
        owner.oid IS NOT NULL
        AND (expected.schema_scope IS NULL OR namespace.oid IS NOT NULL)
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    global_defaults.defaclacl,
                    pg_catalog.acldefault(expected.object_type, owner.oid)
                ) || CASE
                    WHEN expected.schema_scope IS NULL
                    THEN ARRAY[]::aclitem[]
                    ELSE COALESCE(
                        schema_defaults.defaclacl,
                        ARRAY[]::aclitem[]
                    )
                END
            ) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
            WHERE COALESCE(grantee.rolname, 'PUBLIC')
                IN ('PUBLIC', 'anon', 'authenticated')
              AND (
                  expected.object_type IN (
                      'r'::pg_catalog."char",
                      'S'::pg_catalog."char"
                  )
                  OR acl.privilege_type = 'EXECUTE'
              )
        ) AS check_passed
    FROM default_expected AS expected
    LEFT JOIN postgres_role AS owner ON true
    LEFT JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.nspname = expected.schema_scope
    LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
        ON global_defaults.defaclrole = owner.oid
       AND global_defaults.defaclobjtype = expected.object_type
       AND global_defaults.defaclnamespace = 0
    LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
        ON schema_defaults.defaclrole = owner.oid
       AND schema_defaults.defaclobjtype = expected.object_type
       AND schema_defaults.defaclnamespace = namespace.oid
       AND expected.schema_scope IS NOT NULL
),
section_12_checks AS (
    SELECT
        actual.oid IS NOT NULL AS object_present,
        actual.oid IS NOT NULL
        AND actual.relrowsecurity
        AND EXISTS (
            SELECT 1 FROM pg_catalog.pg_policy AS policy
            WHERE policy.polrelid = actual.oid
        ) AS check_passed
    FROM expected_tables AS expected
    LEFT JOIN actual_tables AS actual ON actual.relname = expected.table_name
),
all_checks(section_number, object_present, check_passed, actual_weight) AS (
    SELECT '01', object_present, check_passed, object_present::integer
    FROM section_01_checks
    UNION ALL SELECT '02', object_present, check_passed, object_present::integer
    FROM section_02_checks
    UNION ALL SELECT '03', object_present, check_passed, actual_weight
    FROM section_03_checks
    UNION ALL SELECT '04', object_present, check_passed, object_present::integer
    FROM section_04_checks
    UNION ALL SELECT '05', object_present, check_passed, object_present::integer
    FROM section_05_checks
    UNION ALL SELECT '06', object_present, check_passed, object_present::integer
    FROM section_06_checks
    UNION ALL SELECT '07', object_present, check_passed, object_present::integer
    FROM section_07_checks
    UNION ALL SELECT '08', object_present, check_passed, object_present::integer
    FROM section_08_checks
    UNION ALL SELECT '09', object_present, check_passed, object_present::integer
    FROM section_09_checks
    UNION ALL SELECT '10', object_present, check_passed, object_present::integer
    FROM section_10_checks
    UNION ALL SELECT '11', object_present, check_passed, object_present::integer
    FROM section_11_checks
    UNION ALL SELECT '12', object_present, check_passed, object_present::integer
    FROM section_12_checks
),
expected_counts(section_number, expected_count) AS (
    VALUES
        ('01'::text, 34::bigint), ('02'::text, 24::bigint),
        ('03'::text, 1::bigint), ('04'::text, 1::bigint),
        ('05'::text, 30::bigint), ('06'::text, 12::bigint),
        ('07'::text, 3::bigint), ('08'::text, 1::bigint),
        ('09'::text, 1::bigint), ('10'::text, 34::bigint),
        ('11'::text, 4::bigint), ('12'::text, 34::bigint)
)
SELECT
    expected.section_number,
    expected.expected_count,
    COALESCE(sum(checks.actual_weight), 0) AS actual_count,
    count(*) FILTER (WHERE NOT COALESCE(checks.check_passed, false))
        AS failed_count,
    count(*) = expected.expected_count
        AND COALESCE(sum(checks.actual_weight), 0) = expected.expected_count
        AND count(*) FILTER (WHERE NOT COALESCE(checks.check_passed, false)) = 0
        AS check_passed
FROM expected_counts AS expected
LEFT JOIN all_checks AS checks
    ON checks.section_number = expected.section_number
GROUP BY expected.section_number, expected.expected_count
ORDER BY expected.section_number;
