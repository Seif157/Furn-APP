/*
Phase 3.2C targeted hardening verification -- READ ONLY.

Run each numbered SELECT separately only after an independently reviewed
migration. Every section returns expected_count, actual_count, failed_count,
and check_passed. No statement reads application rows.
*/

-- 01. Hardened customer-profile helper definition and exact grants.
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
        AND candidate.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
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


-- 02. Anonymous review access is exactly seven columns, never table-wide.
WITH role_oids AS (
    SELECT max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid
    FROM pg_catalog.pg_roles
),
expected(column_name, should_select) AS (
    VALUES
        ('id'::name, true),
        ('target_kind'::name, true),
        ('target_product_id'::name, true),
        ('target_marketplace_party_id'::name, true),
        ('rating'::name, true),
        ('comment'::name, true),
        ('created_at'::name, true),
        ('customer_profile_id'::name, false),
        ('target_service_request_id'::name, false)
),
comparison AS (
    SELECT
        expected.column_name,
        pg_catalog.has_column_privilege(
            role_oids.anon_oid,
            'public.review'::pg_catalog.regclass,
            expected.column_name,
            'SELECT'
        ) = expected.should_select AS passed
    FROM expected
    CROSS JOIN role_oids
),
table_grant AS (
    SELECT pg_catalog.has_table_privilege(
        role_oids.anon_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) AS present
    FROM role_oids
)
SELECT
    'review_anon_column_grants'::text AS check_name,
    9::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    9 - count(*) FILTER (WHERE passed)
        + count(*) FILTER (WHERE table_grant.present) AS failed_count,
    count(*) FILTER (WHERE passed) = 9
        AND NOT bool_or(table_grant.present) AS check_passed
FROM comparison
CROSS JOIN table_grant;


-- 03. The anon-only review policy enforces complete public eligibility.
WITH comparison AS (
    SELECT
        policy.policyname IS NOT NULL
        AND policy.permissive = 'PERMISSIVE'
        AND policy.cmd = 'SELECT'
        AND policy.roles = ARRAY['anon']::name[]
        AND lower(policy.qual) LIKE '%target_kind%product%'
        AND lower(policy.qual) LIKE '%target_product_id%is not null%'
        AND lower(policy.qual) LIKE '%target_marketplace_party_id%is null%'
        AND lower(policy.qual) LIKE '%target_service_request_id%is null%'
        AND lower(policy.qual) LIKE '%lifecycle_state%published%'
        AND lower(policy.qual) LIKE '%product_state%'
        AND lower(policy.qual) LIKE '%approval_state%approved%'
        AND lower(policy.qual) LIKE '%party_approval_state%'
        AND lower(policy.qual) LIKE '%category%is_active%'
        AND lower(policy.qual) LIKE '%stock_quantity%0%'
        AND lower(policy.qual) LIKE '%target_kind%marketplace_party%'
        AND lower(policy.qual) NOT LIKE '%is_admin%'
        AND lower(policy.qual) NOT LIKE '%current_customer_profile_id%'
        AS passed
    FROM (SELECT true) AS seed
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = 'review'
       AND policy.policyname = 'phase32c_review_anon_safe_read'
)
SELECT
    'review_anon_policy_eligibility'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 04. Review policies exclude service targets and malformed target columns.
WITH target_policy AS (
    SELECT lower(policy.qual) AS predicate
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename = 'review'
      AND policy.policyname = 'phase32c_review_anon_safe_read'
),
comparison AS (
    SELECT
        predicate NOT LIKE '%''service_request''%'
        AND (
            length(predicate)
            - length(replace(
                predicate,
                'target_service_request_id is null',
                ''
            ))
        ) / length('target_service_request_id is null') = 2
        AND predicate LIKE '%target_product_id is not null%'
        AND predicate LIKE '%target_product_id is null%'
        AND predicate LIKE '%target_marketplace_party_id is not null%'
        AND predicate LIKE '%target_marketplace_party_id is null%'
        AS passed
    FROM target_policy
)
SELECT
    'review_service_and_malformed_rows_excluded'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 1 AS check_passed
FROM comparison;


-- 05. Authenticated raw review reads are restricted to owner or administrator.
WITH comparison AS (
    SELECT
        policy.policyname IS NOT NULL
        AND policy.permissive = 'RESTRICTIVE'
        AND policy.cmd = 'SELECT'
        AND policy.roles = ARRAY['authenticated']::name[]
        AND lower(policy.qual) LIKE '%customer_profile_id%'
        AND lower(policy.qual) LIKE '%current_customer_profile_id%'
        AND lower(policy.qual) LIKE '%is_admin%'
        AND pg_catalog.has_table_privilege(
            'authenticated',
            'public.review'::pg_catalog.regclass,
            'SELECT'
        )
        AND pg_catalog.has_table_privilege(
            'service_role',
            'public.review'::pg_catalog.regclass,
            'SELECT'
        )
        AS passed
    FROM (SELECT true) AS seed
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = 'review'
       AND policy.policyname = 'phase32c_review_authenticated_read_guard'
),
old_policy AS (
    SELECT count(*)::bigint AS old_count
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'review'
      AND policyname = 'review_select_public'
)
SELECT
    'review_authenticated_owner_admin_guard'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE comparison.passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE comparison.passed)
        + old_policy.old_count AS failed_count,
    count(*) FILTER (WHERE comparison.passed) = 1
        AND old_policy.old_count = 0 AS check_passed
FROM comparison
CROSS JOIN old_policy
GROUP BY old_policy.old_count;


-- 06. Service-type reads are active-only for anon/authenticated clients.
WITH expected(policy_name, role_name) AS (
    VALUES
        ('phase32c_service_type_anon_read'::name, 'anon'::name),
        ('phase32c_service_type_authenticated_read'::name, 'authenticated'::name)
),
comparison AS (
    SELECT
        expected.policy_name,
        actual.policyname IS NOT NULL
        AND actual.permissive = 'PERMISSIVE'
        AND actual.cmd = 'SELECT'
        AND actual.roles = ARRAY[expected.role_name]::name[]
        AND btrim(lower(actual.qual), '() ') = 'is_active'
        AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = 'service_type'
       AND actual.policyname = expected.policy_name
),
old_policy AS (
    SELECT count(*)::bigint AS old_count
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'service_type'
      AND policyname = 'service_type_select_public'
)
SELECT
    'service_type_active_only'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE comparison.passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE comparison.passed)
        + old_policy.old_count AS failed_count,
    count(*) FILTER (WHERE comparison.passed) = 2
        AND old_policy.old_count = 0 AS check_passed
FROM comparison
CROSS JOIN old_policy
GROUP BY old_policy.old_count;


-- 07. Anonymous capabilities require approved parties and active services.
WITH comparison AS (
    SELECT
        policy.policyname IS NOT NULL
        AND policy.permissive = 'PERMISSIVE'
        AND policy.cmd = 'SELECT'
        AND policy.roles = ARRAY['anon']::name[]
        AND lower(policy.qual)
            LIKE '%marketplace_party%approval_state%approved%'
        AND lower(policy.qual) LIKE '%service_type%is_active%'
        AND lower(policy.qual) NOT LIKE '%current_marketplace_party_id%'
        AND lower(policy.qual) NOT LIKE '%is_admin%'
        AS passed
    FROM (SELECT true) AS seed
    LEFT JOIN pg_catalog.pg_policies AS policy
        ON policy.schemaname = 'public'
       AND policy.tablename = 'party_capability'
       AND policy.policyname = 'phase32c_party_capability_anon_read'
),
old_policy AS (
    SELECT count(*)::bigint AS old_count
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'party_capability'
      AND policyname = 'party_capability_select'
)
SELECT
    'party_capability_public_scope'::text AS check_name,
    1::bigint AS expected_count,
    count(*) FILTER (WHERE comparison.passed)::bigint AS actual_count,
    1 - count(*) FILTER (WHERE comparison.passed)
        + old_policy.old_count AS failed_count,
    count(*) FILTER (WHERE comparison.passed) = 1
        AND old_policy.old_count = 0 AS check_passed
FROM comparison
CROSS JOIN old_policy
GROUP BY old_policy.old_count;


-- 08. Authenticated directory policies have eligible, owner, and admin paths.
WITH expected(policy_name, required_ingredient) AS (
    VALUES
        ('phase32c_party_capability_authenticated_read'::name, 'approval_state'::text),
        ('phase32c_party_capability_owner_read'::name, 'current_marketplace_party_id'::text),
        ('phase32c_party_capability_admin_read'::name, 'is_admin'::text)
),
comparison AS (
    SELECT
        expected.policy_name,
        actual.policyname IS NOT NULL
        AND actual.permissive = 'PERMISSIVE'
        AND actual.cmd = 'SELECT'
        AND actual.roles = ARRAY['authenticated']::name[]
        AND lower(actual.qual) LIKE
            '%' || expected.required_ingredient || '%'
        AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = 'party_capability'
       AND actual.policyname = expected.policy_name
)
SELECT
    'service_directory_owner_admin_paths'::text AS check_name,
    3::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    3 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 3 AS check_passed
FROM comparison;


-- 09. Furnishing-request has the exact live-confirmed 13-column signature.
WITH expected(
    ordinal_position,
    column_name,
    formatted_type,
    type_oid,
    type_modifier,
    is_not_null,
    default_expression,
    identity_kind,
    generated_kind
) AS (
    VALUES
        (1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (3, 'address_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (4, 'title'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (5, 'requirements_description'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (6, 'reference_image_urls'::name, 'text[]'::text, 'pg_catalog.text[]'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (7, 'budget_min'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 4 + (12 << 16) + 2, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (8, 'budget_max'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 4 + (12 << 16) + 2, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (9, 'requested_timing'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (10, 'offer_deadline'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (11, 'lifecycle_state'::name, 'furnishing_request_state'::text, 'public.furnishing_request_state'::pg_catalog.regtype, -1, true, '''draft''::furnishing_request_state'::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (12, 'created_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, true, 'now()'::text, ''::pg_catalog."char", ''::pg_catalog."char"),
        (13, 'coarse_location'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char", ''::pg_catalog."char")
),
actual AS (
    SELECT
        attribute.attnum::integer AS ordinal_position,
        attribute.attname AS column_name,
        replace(
            pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
            'public.',
            ''
        ) AS formatted_type,
        attribute.atttypid AS type_oid,
        attribute.atttypmod AS type_modifier,
        attribute.attnotnull AS is_not_null,
        replace(
            replace(
                pg_catalog.pg_get_expr(
                    column_default.adbin,
                    column_default.adrelid,
                    false
                ),
                'public.',
                ''
            ),
            'pg_catalog.',
            ''
        ) AS default_expression,
        attribute.attidentity AS identity_kind,
        attribute.attgenerated AS generated_kind
    FROM pg_catalog.pg_attribute AS attribute
    LEFT JOIN pg_catalog.pg_attrdef AS column_default
        ON column_default.adrelid = attribute.attrelid
       AND column_default.adnum = attribute.attnum
    WHERE attribute.attrelid =
          'public.furnishing_request'::pg_catalog.regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
),
missing AS (
    SELECT * FROM expected
    EXCEPT
    SELECT * FROM actual
),
unexpected AS (
    SELECT * FROM actual
    EXCEPT
    SELECT * FROM expected
),
counts AS (
    SELECT
        (SELECT count(*) FROM expected)::bigint AS expected_count,
        (SELECT count(*) FROM actual)::bigint AS actual_count,
        (
            (SELECT count(*) FROM missing)
            + (SELECT count(*) FROM unexpected)
        )::bigint AS failed_count
)
SELECT
    'furnishing_request_exact_inventory'::text AS check_name,
    expected_count,
    actual_count,
    failed_count,
    failed_count = 0
        AND expected_count = 13
        AND actual_count = 13 AS check_passed
FROM counts;


-- 10. Furnishing-request writes are split by operation, never FOR ALL.
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
        AND (
            NOT expected.needs_using
            OR lower(actual.qual) LIKE '%current_customer_profile_id%'
        )
        AND (
            NOT expected.needs_check
            OR lower(actual.with_check) LIKE '%current_customer_profile_id%'
        ) AS passed
    FROM expected
    LEFT JOIN pg_catalog.pg_policies AS actual
        ON actual.schemaname = 'public'
       AND actual.tablename = 'furnishing_request'
       AND actual.policyname = expected.policy_name
),
old_policy AS (
    SELECT count(*)::bigint AS old_count
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'furnishing_request'
      AND policyname = 'furnishing_request_write_own'
)
SELECT
    'furnishing_request_operation_policies'::text AS check_name,
    3::bigint AS expected_count,
    count(*) FILTER (WHERE comparison.passed)::bigint AS actual_count,
    3 - count(*) FILTER (WHERE comparison.passed)
        + old_policy.old_count AS failed_count,
    count(*) FILTER (WHERE comparison.passed) = 3
        AND old_policy.old_count = 0 AS check_passed
FROM comparison
CROSS JOIN old_policy
GROUP BY old_policy.old_count;


-- 11. Draft-only insert, address ownership, and locked-state predicates.
WITH target_policies AS (
    SELECT policyname, cmd, lower(qual) AS qual, lower(with_check) AS with_check
    FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'furnishing_request'
      AND policyname IN (
          'phase32c_furnishing_request_insert_own',
          'phase32c_furnishing_request_update_own',
          'phase32c_furnishing_request_delete_own'
      )
),
comparison AS (
    SELECT
        policyname,
        CASE cmd
            WHEN 'INSERT' THEN
                qual IS NULL
                AND with_check LIKE
                    '%customer_profile_id%current_customer_profile_id%'
                AND with_check LIKE
                    '%lifecycle_state%draft%furnishing_request_state%'
                AND with_check ~ '(^|[^a-z0-9_.])(public\.)?address request_address'
                AND with_check LIKE '%request_address.id%address_id%'
                AND with_check LIKE
                    '%request_address.customer_profile_id%current_customer_profile_id%'
                AND with_check NOT LIKE '%open%'
            WHEN 'UPDATE' THEN
                qual LIKE
                    '%customer_profile_id%current_customer_profile_id%'
                AND qual LIKE '%lifecycle_state%draft%'
                AND qual LIKE '%lifecycle_state%open%'
                AND with_check LIKE
                    '%customer_profile_id%current_customer_profile_id%'
                AND with_check LIKE '%lifecycle_state%draft%'
                AND with_check LIKE '%lifecycle_state%open%'
                AND with_check ~ '(^|[^a-z0-9_.])(public\.)?address request_address'
                AND with_check LIKE '%request_address.id%address_id%'
                AND with_check LIKE
                    '%request_address.customer_profile_id%current_customer_profile_id%'
                AND qual NOT LIKE '%accepted%'
                AND qual NOT LIKE '%withdrawn%'
                AND qual NOT LIKE '%closed%'
                AND with_check NOT LIKE '%accepted%'
                AND with_check NOT LIKE '%withdrawn%'
                AND with_check NOT LIKE '%closed%'
            WHEN 'DELETE' THEN
                with_check IS NULL
                AND qual LIKE
                    '%customer_profile_id%current_customer_profile_id%'
                AND qual LIKE '%lifecycle_state%draft%'
                AND qual LIKE '%lifecycle_state%open%'
                AND qual NOT LIKE '%accepted%'
                AND qual NOT LIKE '%withdrawn%'
                AND qual NOT LIKE '%closed%'
            ELSE false
        END
        AND lower(
            concat_ws(' ', qual, with_check)
        ) NOT LIKE '%or true%'
        AS passed
    FROM target_policies
)
SELECT
    'furnishing_request_lifecycle_and_address_predicates'::text AS check_name,
    3::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    3 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 3 AS check_passed
FROM comparison;


-- 12. Transition functions have exact state directions and safe metadata.
WITH roles AS (
    SELECT max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
expected(function_name, old_state, new_state, forbidden_states) AS (
    VALUES
        (
            'open_furnishing_request'::name,
            'draft'::text,
            'open'::text,
            ARRAY['withdrawn', 'accepted', 'closed']::text[]
        ),
        (
            'withdraw_furnishing_request'::name,
            'open'::text,
            'withdrawn'::text,
            ARRAY['draft', 'accepted', 'closed']::text[]
        )
),
comparison AS (
    SELECT
        expected.function_name,
        function_metadata.oid IS NOT NULL
        AND function_metadata.prorettype =
            'pg_catalog.bool'::pg_catalog.regtype
        AND function_metadata.prolang = (
            SELECT language.oid
            FROM pg_catalog.pg_language AS language
            WHERE language.lanname = 'plpgsql'
        )
        AND function_metadata.provolatile = 'v'::pg_catalog."char"
        AND function_metadata.prosecdef
        AND function_metadata.proowner = roles.postgres_oid
        AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        AND lower(function_metadata.prosrc)
            LIKE '%"public".furnishing_request%'
        AND lower(function_metadata.prosrc) LIKE '%public.customer_profile%'
        AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
        AND lower(function_metadata.prosrc)
            LIKE '%lifecycle_state::text = '''
                || expected.old_state || '''%'
        AND lower(function_metadata.prosrc)
            LIKE '%set lifecycle_state = '''
                || expected.new_state || '''%'
        AND (
            length(lower(function_metadata.prosrc))
            - length(replace(
                lower(function_metadata.prosrc),
                'set lifecycle_state',
                ''
            ))
        ) / length('set lifecycle_state') = 1
        AND position(
            ',' IN split_part(
                split_part(
                    lower(function_metadata.prosrc),
                    'set lifecycle_state',
                    2
                ),
                'where',
                1
            )
        ) = 0
        AND lower(function_metadata.prosrc) NOT LIKE '%or true%'
        AND lower(function_metadata.prosrc) LIKE '%affected_rows = 1%'
        AND NOT EXISTS (
            SELECT 1
            FROM unnest(expected.forbidden_states) AS forbidden(state_name)
            WHERE lower(function_metadata.prosrc)
                LIKE '%''' || forbidden.state_name || '''%'
        ) AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(
            pg_catalog.format(
                'public.%I(pg_catalog.uuid)',
                expected.function_name
            )
        )
)
SELECT
    'furnishing_transition_definitions'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 2 AS check_passed
FROM comparison;


-- 13. Transition EXECUTE is authenticated/service-only without grant option.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
expected(function_name) AS (
    VALUES
        ('open_furnishing_request'::name),
        ('withdraw_furnishing_request'::name)
),
comparison AS (
    SELECT
        expected.function_name,
        function_metadata.oid IS NOT NULL
        AND NOT pg_catalog.has_function_privilege(
            roles.anon_oid,
            function_metadata.oid,
            'EXECUTE'
        )
        AND pg_catalog.has_function_privilege(
            roles.authenticated_oid,
            function_metadata.oid,
            'EXECUTE'
        )
        AND pg_catalog.has_function_privilege(
            roles.service_role_oid,
            function_metadata.oid,
            'EXECUTE'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    function_metadata.proacl,
                    pg_catalog.acldefault(
                        'f'::pg_catalog."char",
                        function_metadata.proowner
                    )
                )
            ) AS acl
            WHERE acl.privilege_type = 'EXECUTE'
              AND (
                  acl.grantee NOT IN (
                      function_metadata.proowner,
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
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(
            pg_catalog.format(
                'public.%I(pg_catalog.uuid)',
                expected.function_name
            )
        )
)
SELECT
    'furnishing_transition_grants'::text AS check_name,
    2::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    2 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 2 AS check_passed
FROM comparison;


-- 14. Exact furnishing INSERT/UPDATE privilege matrix and direct ACL rows.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
    FROM pg_catalog.pg_roles
),
target_columns(
    column_name,
    authenticated_insert,
    authenticated_update
) AS (
    VALUES
        ('id'::name, false, false),
        ('customer_profile_id'::name, true, false),
        ('address_id'::name, true, true),
        ('title'::name, true, true),
        ('requirements_description'::name, true, true),
        ('reference_image_urls'::name, true, true),
        ('budget_min'::name, true, true),
        ('budget_max'::name, true, true),
        ('requested_timing'::name, true, true),
        ('offer_deadline'::name, true, true),
        ('lifecycle_state'::name, false, false),
        ('created_at'::name, false, false),
        ('coarse_location'::name, true, true)
),
target_roles(role_oid, role_name) AS (
    SELECT anon_oid, 'anon'::text FROM roles
    UNION ALL
    SELECT authenticated_oid, 'authenticated'::text FROM roles
    UNION ALL
    SELECT service_role_oid, 'service_role'::text FROM roles
),
operations(privilege_type) AS (
    VALUES ('INSERT'::text), ('UPDATE'::text)
),
effective_comparison AS (
    SELECT
        target_roles.role_name,
        target_columns.column_name,
        operations.privilege_type,
        pg_catalog.has_column_privilege(
            target_roles.role_oid,
            'public.furnishing_request'::pg_catalog.regclass,
            target_columns.column_name,
            operations.privilege_type
        ) IS NOT DISTINCT FROM CASE target_roles.role_name
            WHEN 'anon' THEN false
            WHEN 'authenticated' THEN CASE operations.privilege_type
                WHEN 'INSERT' THEN target_columns.authenticated_insert
                ELSE target_columns.authenticated_update
            END
            ELSE true
        END AS passed
    FROM target_columns
    CROSS JOIN target_roles
    CROSS JOIN operations
),
expected_acl AS (
    SELECT
        target_columns.column_name,
        operation.privilege_type,
        false AS is_grantable
    FROM target_columns
    CROSS JOIN LATERAL (
        VALUES
            ('INSERT'::text, target_columns.authenticated_insert),
            ('UPDATE'::text, target_columns.authenticated_update)
    ) AS operation(privilege_type, allowed)
    WHERE operation.allowed
),
actual_acl AS (
    SELECT
        attribute.attname AS column_name,
        acl.privilege_type,
        acl.is_grantable
    FROM pg_catalog.pg_attribute AS attribute
    CROSS JOIN roles
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        attribute.attacl
    ) AS acl
    WHERE attribute.attrelid =
          'public.furnishing_request'::pg_catalog.regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND acl.grantee = roles.authenticated_oid
      AND acl.privilege_type IN ('INSERT', 'UPDATE')
),
missing_acl AS (
    SELECT * FROM expected_acl
    EXCEPT
    SELECT * FROM actual_acl
),
unexpected_acl AS (
    SELECT * FROM actual_acl
    EXCEPT
    SELECT * FROM expected_acl
),
table_grants AS (
    SELECT privilege_type
    FROM roles
    CROSS JOIN operations
    WHERE pg_catalog.has_table_privilege(
        roles.authenticated_oid,
        'public.furnishing_request'::pg_catalog.regclass,
        operations.privilege_type
    )
),
counts AS (
    SELECT
        99::bigint AS expected_count,
        (
            (SELECT count(*) FILTER (WHERE passed) FROM effective_comparison)
            + (SELECT count(*) FROM expected_acl)
            - (SELECT count(*) FROM missing_acl)
            + 2
            - (SELECT count(*) FROM table_grants)
        )::bigint AS actual_count,
        (
            78
            - (SELECT count(*) FILTER (WHERE passed) FROM effective_comparison)
            + (SELECT count(*) FROM missing_acl)
            + (SELECT count(*) FROM unexpected_acl)
            + (SELECT count(*) FROM table_grants)
        )::bigint AS failed_count
)
SELECT
    'furnishing_request_exact_column_privileges'::text AS check_name,
    expected_count,
    actual_count,
    failed_count,
    failed_count = 0 AND actual_count = expected_count AS check_passed
FROM counts;


-- 15. Financial view remains invoker-rights and authenticated SELECT-only.
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
            WHERE acl.grantee IN (
                0,
                roles.anon_oid,
                roles.authenticated_oid
            )
              AND (
                  acl.privilege_type <> 'SELECT'
                  OR acl.is_grantable
              )
        )
        AND EXISTS (
            SELECT 1
            FROM information_schema.views AS information_view
            WHERE information_view.table_schema = 'public'
              AND information_view.table_name =
                  'order_financial_position'
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


-- 16. The exact 30 Phase 3.2B catalogue policies remain present.
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


-- 17. Required service_role paths remain effective.
WITH roles AS (
    SELECT max(oid) FILTER (WHERE rolname = 'service_role') AS role_oid
    FROM pg_catalog.pg_roles
),
checks(check_name, passed) AS (
    SELECT
        'customer_profile_helper_execute',
        pg_catalog.has_function_privilege(
            roles.role_oid,
            'public.current_customer_profile_id()'::pg_catalog.regprocedure,
            'EXECUTE'
        )
    FROM roles
    UNION ALL
    SELECT
        'open_transition_execute',
        pg_catalog.has_function_privilege(
            roles.role_oid,
            'public.open_furnishing_request(pg_catalog.uuid)'::pg_catalog.regprocedure,
            'EXECUTE'
        )
    FROM roles
    UNION ALL
    SELECT
        'withdraw_transition_execute',
        pg_catalog.has_function_privilege(
            roles.role_oid,
            'public.withdraw_furnishing_request(pg_catalog.uuid)'::pg_catalog.regprocedure,
            'EXECUTE'
        )
    FROM roles
    UNION ALL
    SELECT
        'raw_review_select',
        pg_catalog.has_table_privilege(
            roles.role_oid,
            'public.review'::pg_catalog.regclass,
            'SELECT'
        )
    FROM roles
    UNION ALL
    SELECT
        'financial_view_select',
        pg_catalog.has_table_privilege(
            roles.role_oid,
            'public.order_financial_position'::pg_catalog.regclass,
            'SELECT'
        )
    FROM roles
)
SELECT
    'service_role_functional'::text AS check_name,
    5::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    5 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 5 AS check_passed
FROM checks;


-- 18. Client roles have no elevation or service_role membership.
WITH roles AS (
    SELECT max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid
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


-- 19. PUBLIC has no privilege on targeted relations/functions.
WITH unexpected_privileges AS (
    SELECT relation.relname::text AS object_name, acl.privilege_type
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
          'order_financial_position'
      )
      AND acl.grantee = 0
    UNION ALL
    SELECT
        relation.relname::text || '.' || attribute.attname::text,
        acl.privilege_type
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_attribute AS attribute
        ON attribute.attrelid = relation.oid
       AND attribute.attnum > 0
       AND NOT attribute.attisdropped
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        attribute.attacl
    ) AS acl
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'review'
      AND acl.grantee = 0
    UNION ALL
    SELECT function_metadata.proname::text, acl.privilege_type
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
    WHERE function_metadata.oid IN (
        'public.current_customer_profile_id()'::pg_catalog.regprocedure,
        'public.open_furnishing_request(pg_catalog.uuid)'::pg_catalog.regprocedure,
        'public.withdraw_furnishing_request(pg_catalog.uuid)'::pg_catalog.regprocedure
    )
      AND acl.grantee = 0
)
SELECT
    'unexpected_public_privileges'::text AS check_name,
    0::bigint AS expected_count,
    count(*)::bigint AS actual_count,
    count(*)::bigint AS failed_count,
    count(*) = 0 AS check_passed
FROM unexpected_privileges;


-- 20. Exact managed Storage default ACL signature remains unchanged.
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
object_type_mapping(catalog_object_type, acldefault_object_type) AS (
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
      -- The owner's own privileges are not grants to anyone; the applied
      -- 3.2B check excludes them the same way.
      AND acl.grantee <> default_acl.defaclrole
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
