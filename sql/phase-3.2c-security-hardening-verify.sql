/*
Phase 3.2C targeted hardening verification -- READ ONLY.

Run each numbered SELECT separately only after a reviewed migration attempt.
Every section returns expected_count, actual_count, failed_count, and
check_passed. No statement reads application rows.
*/

-- 01. Customer-profile helper definition, owner, mode, path, and exact grants.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
candidate AS (
    SELECT function_metadata.*
    FROM pg_catalog.pg_proc AS function_metadata
    WHERE function_metadata.oid = pg_catalog.to_regprocedure(
        'public.current_customer_profile_id()'
    )
),
comparison AS (
    SELECT
        candidate.oid IS NOT NULL
        AND candidate.pronargs = 0
        AND candidate.prorettype = 'pg_catalog.uuid'::pg_catalog.regtype
        AND candidate.prolang = (
            SELECT language.oid
            FROM pg_catalog.pg_language AS language
            WHERE language.lanname = 'sql'
        )
        AND candidate.provolatile = 's'::pg_catalog."char"
        AND candidate.prosecdef
        AND candidate.proowner = roles.postgres_oid
        AND candidate.proconfig = ARRAY['search_path=']::text[]
        AND lower(candidate.prosrc) LIKE '%public.customer_profile%'
        AND lower(candidate.prosrc) LIKE '%auth.uid()%'
        AND NOT pg_catalog.has_function_privilege(
            roles.anon_oid,
            candidate.oid,
            'EXECUTE'
        )
        AND pg_catalog.has_function_privilege(
            roles.authenticated_oid,
            candidate.oid,
            'EXECUTE'
        )
        AND pg_catalog.has_function_privilege(
            roles.service_role_oid,
            candidate.oid,
            'EXECUTE'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS acl_function
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    acl_function.proacl,
                    pg_catalog.acldefault(
                        'f'::pg_catalog."char",
                        acl_function.proowner
                    )
                )
            ) AS acl
            WHERE acl_function.oid = candidate.oid
              AND acl.privilege_type = 'EXECUTE'
              AND (
                  acl.grantee NOT IN (
                      roles.postgres_oid,
                      roles.authenticated_oid,
                      roles.service_role_oid
                  )
                  OR (
                      acl.grantee IN (
                          roles.authenticated_oid,
                          roles.service_role_oid
                      )
                      AND acl.is_grantable
                  )
              )
        ) AS passed
    FROM roles
    LEFT JOIN candidate ON true
)
SELECT
    'customer_profile_helper'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 02. Anonymous callers have no raw review SELECT path.
WITH role_oids AS (
    SELECT max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid
    FROM pg_catalog.pg_roles
),
comparison AS (
    SELECT
        NOT pg_catalog.has_table_privilege(
            role_oids.anon_oid,
            'public.review'::pg_catalog.regclass,
            'SELECT'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    relation.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        relation.relowner
                    )
                )
            ) AS acl
            WHERE relation.oid = 'public.review'::pg_catalog.regclass
              AND acl.grantee = 0
              AND acl.privilege_type = 'SELECT'
        ) AS passed
    FROM role_oids
)
SELECT
    'raw_review_anon_denial'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 03. Public review view has the exact projection, predicates, grants, and
-- non-updatable owner-rights safety envelope.
WITH expected_columns(column_name) AS (
    VALUES
        ('id'::name),
        ('target_kind'::name),
        ('target_product_id'::name),
        ('target_marketplace_party_id'::name),
        ('rating'::name),
        ('comment'::name),
        ('created_at'::name)
),
actual_columns(column_name) AS (
    SELECT column_metadata.column_name::name
    FROM information_schema.columns AS column_metadata
    WHERE column_metadata.table_schema = 'public'
      AND column_metadata.table_name = 'public_review'
),
column_drift AS (
    (SELECT column_name FROM expected_columns
     EXCEPT
     SELECT column_name FROM actual_columns)
    UNION ALL
    (SELECT column_name FROM actual_columns
     EXCEPT
     SELECT column_name FROM expected_columns)
),
roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
view_metadata AS (
    SELECT
        relation.oid,
        relation.relowner,
        relation.reloptions,
        pg_catalog.pg_get_viewdef(relation.oid, true) AS definition
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'public_review'
      AND relation.relkind = 'v'::pg_catalog."char"
),
comparison AS (
    SELECT
        view_metadata.oid IS NOT NULL
        AND pg_catalog.pg_get_userbyid(view_metadata.relowner) = 'postgres'
        AND view_metadata.reloptions @> ARRAY['security_barrier=true']::text[]
        AND NOT COALESCE(
            view_metadata.reloptions @> ARRAY['security_invoker=true']::text[],
            false
        )
        AND NOT EXISTS (SELECT 1 FROM column_drift)
        AND EXISTS (
            SELECT 1
            FROM information_schema.views AS information_view
            WHERE information_view.table_schema = 'public'
              AND information_view.table_name = 'public_review'
              AND information_view.is_updatable = 'NO'
        )
        AND pg_catalog.has_table_privilege(
            roles.anon_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND pg_catalog.has_table_privilege(
            roles.authenticated_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND pg_catalog.has_table_privilege(
            roles.service_role_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS acl_view
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    acl_view.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        acl_view.relowner
                    )
                )
            ) AS acl
            WHERE acl_view.oid = view_metadata.oid
              AND acl.grantee IN (
                  0,
                  roles.anon_oid,
                  roles.authenticated_oid,
                  roles.service_role_oid
              )
              AND (
                  acl.privilege_type <> 'SELECT'
                  OR acl.is_grantable
              )
        )
        AND lower(view_metadata.definition) LIKE '%lifecycle_state%published%'
        AND lower(view_metadata.definition) LIKE '%product_state%'
        AND lower(view_metadata.definition) LIKE '%approval_state%approved%'
        AND lower(view_metadata.definition) LIKE '%party_approval_state%'
        AND lower(view_metadata.definition) LIKE '%is_active%'
        AND lower(view_metadata.definition) LIKE '%stock_quantity%0%'
        AS passed
    FROM roles
    LEFT JOIN view_metadata ON true
)
SELECT
    'safe_public_review_projection'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 04. No service-request review can leave the public projection.
WITH view_metadata AS (
    SELECT pg_catalog.pg_get_viewdef(relation.oid, true) AS definition
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'public_review'
      AND relation.relkind = 'v'::pg_catalog."char"
),
comparison AS (
    SELECT
        lower(definition) NOT LIKE '%customer_profile_id%'
        AND lower(definition) NOT LIKE '%''service_request''%'
        AND (
            length(lower(definition))
            - length(replace(lower(definition), 'target_service_request_id', ''))
        ) / length('target_service_request_id') = 2
        AND (
            length(lower(definition))
            - length(replace(
                lower(definition),
                'target_service_request_id is null',
                ''
            ))
        ) / length('target_service_request_id is null') = 2
        AS passed
    FROM view_metadata
)
SELECT
    'public_service_request_review_denial'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 05. Service-type anonymous visibility is active-only.
WITH comparison AS (
    SELECT
        policy.policyname IS NOT NULL
        AND policy.permissive = 'RESTRICTIVE'
        AND policy.cmd = 'SELECT'
        AND policy.roles = ARRAY['anon']::name[]
        AND lower(policy.qual) LIKE '%is_active%'
        AND lower(policy.qual) NOT LIKE '%is_admin%'
        AS passed
    FROM (SELECT true) AS seed
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = 'service_type'
       AND policy.policyname = 'phase32c_service_type_anon_read_guard'
)
SELECT
    'active_service_type_public_read'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 06. Anonymous capability visibility requires approved party and active type.
WITH comparison AS (
    SELECT
        policy.policyname IS NOT NULL
        AND policy.permissive = 'RESTRICTIVE'
        AND policy.cmd = 'SELECT'
        AND policy.roles = ARRAY['anon']::name[]
        AND lower(policy.qual) LIKE '%marketplace_party%approval_state%approved%'
        AND lower(policy.qual) LIKE '%service_type%is_active%'
        AND lower(policy.qual) NOT LIKE '%current_marketplace_party_id%'
        AND lower(policy.qual) NOT LIKE '%is_admin%'
        AS passed
    FROM (SELECT true) AS seed
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = 'party_capability'
       AND policy.policyname = 'phase32c_party_capability_anon_read_guard'
)
SELECT
    'safe_public_party_capability'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 07. Authenticated service-directory guards retain owner/admin paths.
WITH expected(table_name, policy_name, owner_required) AS (
    VALUES
        (
            'service_type'::name,
            'phase32c_service_type_authenticated_read_guard'::name,
            false
        ),
        (
            'party_capability'::name,
            'phase32c_party_capability_authenticated_read_guard'::name,
            true
        )
),
comparison AS (
    SELECT
        expected.policy_name,
        actual.policyname IS NOT NULL
        AND actual.permissive = 'RESTRICTIVE'
        AND actual.cmd = 'SELECT'
        AND actual.roles = ARRAY['authenticated']::name[]
        AND lower(actual.qual) LIKE '%is_admin%'
        AND (
            NOT expected.owner_required
            OR lower(actual.qual) LIKE '%current_marketplace_party_id%'
        ) AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = expected.table_name
       AND actual.policyname = expected.policy_name
)
SELECT
    'service_directory_owner_admin_paths'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 2 AS check_passed
FROM comparison;


-- 08. Furnishing-request write access is operation-specific, never FOR ALL.
WITH expected(policy_name, command_name, needs_using, needs_check) AS (
    VALUES
        ('phase32c_furnishing_request_insert_own'::name, 'INSERT'::text, false, true),
        ('phase32c_furnishing_request_update_own'::name, 'UPDATE'::text, true, true),
        ('phase32c_furnishing_request_delete_own'::name, 'DELETE'::text, true, false)
),
comparison AS (
    SELECT
        expected.policy_name,
        actual.policyname IS NOT NULL
        AND actual.permissive = 'PERMISSIVE'
        AND actual.cmd = expected.command_name
        AND actual.roles = ARRAY['authenticated']::name[]
        AND (NOT expected.needs_using OR actual.qual IS NOT NULL)
        AND (NOT expected.needs_check OR actual.with_check IS NOT NULL)
        AND lower(COALESCE(actual.qual, '')) LIKE
            CASE WHEN expected.needs_using
                 THEN '%current_customer_profile_id%'
                 ELSE lower(COALESCE(actual.qual, '')) END
        AND lower(COALESCE(actual.with_check, '')) LIKE
            CASE WHEN expected.needs_check
                 THEN '%current_customer_profile_id%'
                 ELSE lower(COALESCE(actual.with_check, '')) END
        AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = 'furnishing_request'
       AND actual.policyname = expected.policy_name
),
legacy_policy AS (
    SELECT count(*)::bigint AS legacy_count
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename = 'furnishing_request'
      AND policy.policyname = 'furnishing_request_write_own'
),
counts AS (
    SELECT
        count(*) FILTER (WHERE comparison.passed)::bigint AS passed_count,
        legacy_policy.legacy_count
    FROM comparison
    CROSS JOIN legacy_policy
    GROUP BY legacy_policy.legacy_count
)
SELECT
    'furnishing_request_operation_policies'::text AS check_name,
    3::bigint AS expected_count,
    passed_count AS actual_count,
    3 - passed_count + legacy_count AS failed_count,
    passed_count = 3 AND legacy_count = 0 AS check_passed
FROM counts;


-- 09. Ordinary customers cannot update/delete locked lifecycle states.
WITH target_policies AS (
    SELECT policy.policyname, policy.cmd, policy.qual, policy.with_check
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename = 'furnishing_request'
      AND policy.policyname IN (
          'phase32c_furnishing_request_update_own',
          'phase32c_furnishing_request_delete_own'
      )
),
comparison AS (
    SELECT
        policyname,
        lower(COALESCE(qual, '')) LIKE '%draft%'
        AND lower(COALESCE(qual, '')) LIKE '%open%'
        AND lower(COALESCE(qual, '')) NOT LIKE '%accepted%'
        AND lower(COALESCE(qual, '')) NOT LIKE '%withdrawn%'
        AND lower(COALESCE(qual, '')) NOT LIKE '%closed%'
        AND (
            cmd <> 'UPDATE'
            OR (
                lower(COALESCE(with_check, '')) LIKE '%draft%'
                AND lower(COALESCE(with_check, '')) LIKE '%open%'
                AND lower(COALESCE(with_check, '')) NOT LIKE '%accepted%'
                AND lower(COALESCE(with_check, '')) NOT LIKE '%withdrawn%'
                AND lower(COALESCE(with_check, '')) NOT LIKE '%closed%'
            )
        ) AS passed
    FROM target_policies
)
SELECT
    'furnishing_request_locked_states'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 2 AS check_passed
FROM comparison;


-- 10. Financial view remains invoker-rights and authenticated SELECT-only.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
view_metadata AS (
    SELECT relation.*
    FROM pg_catalog.pg_class AS relation
    WHERE relation.oid =
        'public.order_financial_position'::pg_catalog.regclass
      AND relation.relkind = 'v'::pg_catalog."char"
),
comparison AS (
    SELECT
        view_metadata.reloptions @> ARRAY['security_invoker=true']::text[]
        AND NOT pg_catalog.has_table_privilege(
            roles.anon_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND pg_catalog.has_table_privilege(
            roles.authenticated_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND pg_catalog.has_table_privilege(
            roles.service_role_oid,
            view_metadata.oid,
            'SELECT'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    view_metadata.relacl,
                    pg_catalog.acldefault(
                        'r'::pg_catalog."char",
                        view_metadata.relowner
                    )
                )
            ) AS acl
            WHERE acl.grantee IN (0, roles.anon_oid, roles.authenticated_oid)
              AND (
                  acl.privilege_type <> 'SELECT'
                  OR acl.is_grantable
              )
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.views AS information_view
            WHERE information_view.table_schema = 'public'
              AND information_view.table_name = 'order_financial_position'
              AND information_view.is_updatable = 'NO'
        ) AS passed
    FROM roles
    CROSS JOIN view_metadata
)
SELECT
    'financial_view_authenticated_select_only'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 11. All Phase 3.2B catalogue policies remain present and unchanged in role,
-- command, and mode; run the Phase 3.2B verifier for full predicate proofs.
WITH expected(table_name, policy_name, role_name, mode_name) AS (
    VALUES
        ('category'::name, 'phase32b_category_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('category'::name, 'phase32b_category_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text),
        ('custom_offering'::name, 'custom_offering_select_published_or_own'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('custom_offering'::name, 'phase32b_custom_offering_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product'::name, 'product_select_published_or_own'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product'::name, 'phase32b_product_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product'::name, 'phase32b_product_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('product'::name, 'phase32b_product_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product'::name, 'phase32b_product_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text),
        ('product_color'::name, 'product_color_select'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_color'::name, 'phase32b_product_color_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('product_color'::name, 'phase32b_product_color_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product_color'::name, 'phase32b_product_color_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text),
        ('product_image'::name, 'product_image_select'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_image'::name, 'phase32b_product_image_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('product_image'::name, 'phase32b_product_image_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product_image'::name, 'phase32b_product_image_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text),
        ('product_3d_model'::name, 'product_3d_model_select'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product_3d_model'::name, 'phase32b_product_3d_model_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text),
        ('product_enrichment_assignment'::name, 'product_enrichment_assignment_select'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_owner_read'::name, 'authenticated'::text, 'PERMISSIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read'::name, 'anon'::text, 'PERMISSIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read_guard'::name, 'anon'::text, 'RESTRICTIVE'::text),
        ('product_enrichment_assignment'::name, 'phase32b_enrichment_authenticated_read_guard'::name, 'authenticated'::text, 'RESTRICTIVE'::text)
),
comparison AS (
    SELECT
        expected.policy_name,
        actual.policyname IS NOT NULL
        AND actual.roles = ARRAY[expected.role_name]::name[]
        AND actual.cmd = 'SELECT'
        AND actual.permissive = expected.mode_name
        AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = expected.table_name
       AND actual.policyname = expected.policy_name
)
SELECT
    'phase32b_catalogue_policies_unchanged'::text AS check_name,
    30::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    30 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 30 AS check_passed
FROM comparison;


-- 12. Required service_role paths remain effective.
WITH roles AS (
    SELECT max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
checks(check_name, passed) AS (
    SELECT
        'customer_profile_helper_execute',
        pg_catalog.has_function_privilege(
            roles.service_role_oid,
            'public.current_customer_profile_id()'::pg_catalog.regprocedure,
            'EXECUTE'
        )
    FROM roles
    UNION ALL
    SELECT
        'public_review_select',
        pg_catalog.has_table_privilege(
            roles.service_role_oid,
            'public.public_review'::pg_catalog.regclass,
            'SELECT'
        )
    FROM roles
    UNION ALL
    SELECT
        'financial_view_select',
        pg_catalog.has_table_privilege(
            roles.service_role_oid,
            'public.order_financial_position'::pg_catalog.regclass,
            'SELECT'
        )
    FROM roles
)
SELECT
    'service_role_functional'::text AS check_name,
    3::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    3 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 3 AS check_passed
FROM checks;


-- 13. Client roles have no elevated attributes or service-role membership.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
clients AS (
    SELECT role_row.*
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname IN ('anon', 'authenticated')
),
comparison AS (
    SELECT
        client.rolname,
        NOT client.rolsuper
        AND NOT client.rolbypassrls
        AND NOT client.rolcreatedb
        AND NOT client.rolcreaterole
        AND NOT pg_catalog.pg_has_role(
            client.oid,
            roles.service_role_oid,
            'MEMBER'
        ) AS passed
    FROM clients AS client
    CROSS JOIN roles
)
SELECT
    'client_role_separation'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 2 AS check_passed
FROM comparison;


-- 14. PUBLIC has no unexpected target-object privileges. PUBLIC schema USAGE
-- remains intentional and is inspected through ACL grantee OID zero.
WITH unexpected_privileges AS (
    SELECT relation.relname, acl.privilege_type
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            relation.relacl,
            pg_catalog.acldefault(
                'r'::pg_catalog."char",
                relation.relowner
            )
        )
    ) AS acl
    WHERE namespace.nspname = 'public'
      AND relation.relname IN (
          'review',
          'public_review',
          'order_financial_position'
      )
      AND acl.grantee = 0
    UNION ALL
    SELECT function_metadata.proname, acl.privilege_type
    FROM pg_catalog.pg_proc AS function_metadata
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            function_metadata.proacl,
            pg_catalog.acldefault(
                'f'::pg_catalog."char",
                function_metadata.proowner
            )
        )
    ) AS acl
    WHERE function_metadata.oid =
          'public.current_customer_profile_id()'::pg_catalog.regprocedure
      AND acl.grantee = 0
)
SELECT
    'unexpected_public_privileges'::text AS check_name,
    0::bigint AS expected_count,
    count(*)::bigint AS actual_count,
    count(*)::bigint AS failed_count,
    count(*) = 0 AS check_passed
FROM unexpected_privileges;


-- 15. Exact managed storage default ACL signature remains unchanged.
WITH role_metadata(role_name, role_oid) AS (
    SELECT expected.role_name, actual.oid
    FROM (
        VALUES
            ('anon'::name),
            ('authenticated'::name),
            ('service_role'::name)
    ) AS expected(role_name)
    LEFT JOIN pg_catalog.pg_roles AS actual
        ON actual.rolname = expected.role_name
),
object_privileges(
    catalog_object_type,
    acldefault_object_type,
    privilege_type
) AS (
    VALUES
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'SELECT'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'INSERT'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'UPDATE'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'DELETE'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'TRUNCATE'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'REFERENCES'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'TRIGGER'::text),
        ('r'::pg_catalog."char", 'r'::pg_catalog."char", 'MAINTAIN'::text),
        ('S'::pg_catalog."char", 's'::pg_catalog."char", 'SELECT'::text),
        ('S'::pg_catalog."char", 's'::pg_catalog."char", 'UPDATE'::text),
        ('S'::pg_catalog."char", 's'::pg_catalog."char", 'USAGE'::text),
        ('f'::pg_catalog."char", 'f'::pg_catalog."char", 'EXECUTE'::text)
),
object_type_mapping(
    catalog_object_type,
    acldefault_object_type
) AS (
    VALUES
        ('r'::pg_catalog."char", 'r'::pg_catalog."char"),
        ('S'::pg_catalog."char", 's'::pg_catalog."char"),
        ('f'::pg_catalog."char", 'f'::pg_catalog."char")
),
expected_signature AS (
    SELECT
        'postgres'::name AS owner_name,
        'storage'::name AS schema_name,
        privilege.catalog_object_type,
        role.role_oid AS grantee,
        privilege.privilege_type,
        false AS is_grantable
    FROM role_metadata AS role
    CROSS JOIN object_privileges AS privilege
    WHERE privilege.privilege_type <> 'MAINTAIN'
       OR current_setting('server_version_num')::integer >= 170000
),
actual_signature AS (
    SELECT
        owner_role.rolname AS owner_name,
        namespace.nspname AS schema_name,
        default_acl.defaclobjtype AS catalog_object_type,
        acl.grantee,
        acl.privilege_type,
        acl.is_grantable
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_roles AS owner_role
        ON owner_role.oid = default_acl.defaclrole
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = default_acl.defaclnamespace
    LEFT JOIN object_type_mapping AS object_type
        ON object_type.catalog_object_type = default_acl.defaclobjtype
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            default_acl.defaclacl,
            pg_catalog.acldefault(
                object_type.acldefault_object_type,
                default_acl.defaclrole
            )
        )
    ) AS acl
    WHERE owner_role.rolname = 'postgres'
      AND namespace.nspname = 'storage'
),
missing AS (
    SELECT * FROM expected_signature
    EXCEPT
    SELECT * FROM actual_signature
),
unexpected AS (
    SELECT * FROM actual_signature
    EXCEPT
    SELECT * FROM expected_signature
),
counts AS (
    SELECT
        (SELECT count(*) FROM expected_signature) AS expected_count,
        (SELECT count(*) FROM actual_signature) AS actual_count,
        (SELECT count(*) FROM missing)
            + (SELECT count(*) FROM unexpected) AS failed_count
)
SELECT
    'managed_storage_default_acl_unchanged'::text AS check_name,
    expected_count,
    actual_count,
    failed_count,
    failed_count = 0 AS check_passed
FROM counts;


-- 16. Verification-section shape summary. Run and retain Sections 01-15; this
-- structural summary does not substitute for their individual result rows.
WITH expected_sections(section_number) AS (
    SELECT generate_series(1, 15)
),
actual_sections(section_number) AS (
    VALUES
        (1), (2), (3), (4), (5),
        (6), (7), (8), (9), (10),
        (11), (12), (13), (14), (15)
)
SELECT
    'verification_section_inventory'::text AS check_name,
    (SELECT count(*) FROM expected_sections)::bigint AS expected_count,
    (SELECT count(*) FROM actual_sections)::bigint AS actual_count,
    (
        SELECT count(*)
        FROM (
            (SELECT section_number FROM expected_sections
             EXCEPT
             SELECT section_number FROM actual_sections)
            UNION ALL
            (SELECT section_number FROM actual_sections
             EXCEPT
             SELECT section_number FROM expected_sections)
        ) AS drift
    )::bigint AS failed_count,
    NOT EXISTS (
        (SELECT section_number FROM expected_sections
         EXCEPT
         SELECT section_number FROM actual_sections)
        UNION ALL
        (SELECT section_number FROM actual_sections
         EXCEPT
         SELECT section_number FROM expected_sections)
    ) AS check_passed;
