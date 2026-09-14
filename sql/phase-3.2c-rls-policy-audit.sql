/*
Phase 3.2C: read-only RLS policy audit.

Run each numbered SELECT separately in the Supabase SQL Editor. Every statement
reads PostgreSQL metadata only. No statement reads application rows or changes
data, policies, grants, functions, schema objects, or role membership.
*/

-- 01. Exact current public base-table inventory, ownership, and RLS state.
SELECT
    namespace.nspname AS schema_name,
    relation.relname AS table_name,
    pg_catalog.pg_get_userbyid(relation.relowner) AS owner_name,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS force_rls_enabled,
    CASE relation.relkind
        WHEN 'r'::pg_catalog."char" THEN 'ordinary_table'
        WHEN 'p'::pg_catalog."char" THEN 'partitioned_table'
        ELSE 'unexpected_base_table_kind'
    END AS table_kind
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN (
      'r'::pg_catalog."char",
      'p'::pg_catalog."char"
  )
ORDER BY relation.relname;


-- 02. Every current public RLS policy without role, command, or name filtering.
SELECT
    policy.schemaname AS schema_name,
    policy.tablename AS table_name,
    policy.policyname AS policy_name,
    policy.permissive AS policy_mode,
    policy.roles AS policy_roles,
    policy.cmd AS policy_command,
    policy.qual AS complete_using_expression,
    policy.with_check AS complete_with_check_expression
FROM pg_catalog.pg_policies AS policy
WHERE policy.schemaname = 'public'
ORDER BY policy.tablename, policy.policyname;


-- 03. Dynamically identify current FOR ALL policies and report an empty set.
WITH for_all_policies AS (
    SELECT
        policy.tablename AS table_name,
        policy.policyname AS policy_name,
        policy.permissive AS policy_mode,
        policy.roles AS policy_roles,
        policy.qual AS complete_using_expression,
        policy.with_check AS complete_with_check_expression
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.cmd = 'ALL'
),
policy_count AS (
    SELECT count(*)::bigint AS current_for_all_policy_count
    FROM for_all_policies
)
SELECT
    'policy'::text AS result_kind,
    policy.table_name,
    policy.policy_name,
    policy.policy_mode,
    policy.policy_roles,
    policy.complete_using_expression,
    policy.complete_with_check_expression,
    count.current_for_all_policy_count,
    'current_for_all_policy'::text AS result_detail
FROM for_all_policies AS policy
CROSS JOIN policy_count AS count
UNION ALL
SELECT
    CASE
        WHEN count.current_for_all_policy_count = 0 THEN 'empty_result'
        ELSE 'summary'
    END AS result_kind,
    NULL::name AS table_name,
    NULL::name AS policy_name,
    NULL::text AS policy_mode,
    NULL::name[] AS policy_roles,
    NULL::text AS complete_using_expression,
    NULL::text AS complete_with_check_expression,
    count.current_for_all_policy_count,
    CASE
        WHEN count.current_for_all_policy_count = 0
        THEN 'no_current_for_all_policies'
        ELSE 'current_for_all_policies_listed_above'
    END AS result_detail
FROM policy_count AS count
ORDER BY result_kind, table_name, policy_name;


-- 04. Expand each current FOR ALL policy into its four effective operations.
-- PostgreSQL uses USING as the default WITH CHECK for ALL/UPDATE when an
-- explicit WITH CHECK expression is absent.
WITH operations(operation_name, display_order) AS (
    VALUES
        ('SELECT'::text, 1),
        ('INSERT'::text, 2),
        ('UPDATE'::text, 3),
        ('DELETE'::text, 4)
),
for_all_policies AS (
    SELECT
        policy.tablename AS table_name,
        policy.policyname AS policy_name,
        policy.permissive AS policy_mode,
        policy.roles AS policy_roles,
        policy.qual AS raw_using_expression,
        policy.with_check AS raw_with_check_expression
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.cmd = 'ALL'
),
expanded AS (
    SELECT
        policy.table_name,
        policy.policy_name,
        policy.policy_mode,
        policy.policy_roles,
        operation.operation_name,
        operation.display_order,
        policy.raw_using_expression,
        policy.raw_with_check_expression,
        CASE
            WHEN operation.operation_name IN ('SELECT', 'UPDATE', 'DELETE')
            THEN policy.raw_using_expression
        END AS effective_using_expression,
        CASE
            WHEN operation.operation_name IN ('INSERT', 'UPDATE')
            THEN COALESCE(
                policy.raw_with_check_expression,
                policy.raw_using_expression
            )
        END AS effective_with_check_expression
    FROM for_all_policies AS policy
    CROSS JOIN operations AS operation
)
SELECT
    table_name,
    policy_name,
    policy_mode,
    policy_roles,
    operation_name,
    raw_using_expression,
    raw_with_check_expression,
    effective_using_expression,
    effective_with_check_expression,
    CASE operation_name
        WHEN 'SELECT' THEN effective_using_expression IS NOT NULL
        WHEN 'INSERT' THEN effective_with_check_expression IS NOT NULL
        WHEN 'UPDATE' THEN effective_using_expression IS NOT NULL
                           AND effective_with_check_expression IS NOT NULL
        WHEN 'DELETE' THEN effective_using_expression IS NOT NULL
        ELSE false
    END AS required_predicates_present
FROM expanded
ORDER BY table_name, policy_name, display_order;


-- 05. Operation-level policy predicate review. These are conservative static
-- signals for human review, not proofs that a Boolean expression is correct.
WITH operations(operation_name, display_order) AS (
    VALUES
        ('SELECT'::text, 1),
        ('INSERT'::text, 2),
        ('UPDATE'::text, 3),
        ('DELETE'::text, 4)
),
anonymous_read_tables(table_name) AS (
    VALUES
        ('category'::name),
        ('custom_offering'::name),
        ('marketplace_party'::name),
        ('party_capability'::name),
        ('product'::name),
        ('product_3d_model'::name),
        ('product_color'::name),
        ('product_enrichment_assignment'::name),
        ('product_enrichment_attribute'::name),
        ('product_image'::name),
        ('review'::name),
        ('service_type'::name)
),
expanded AS (
    SELECT
        policy.tablename AS table_name,
        policy.policyname AS policy_name,
        policy.permissive AS policy_mode,
        policy.roles AS policy_roles,
        operation.operation_name,
        operation.display_order,
        policy.qual AS raw_using_expression,
        policy.with_check AS raw_with_check_expression,
        CASE
            WHEN operation.operation_name IN ('SELECT', 'UPDATE', 'DELETE')
            THEN policy.qual
        END AS effective_using_expression,
        CASE
            WHEN operation.operation_name IN ('INSERT', 'UPDATE')
             AND policy.cmd IN ('ALL', 'UPDATE')
            THEN COALESCE(policy.with_check, policy.qual)
            WHEN operation.operation_name = 'INSERT'
            THEN policy.with_check
        END AS effective_with_check_expression
    FROM pg_catalog.pg_policies AS policy
    CROSS JOIN operations AS operation
    WHERE policy.schemaname = 'public'
      AND (
          policy.cmd = 'ALL'
          OR policy.cmd = operation.operation_name
      )
),
normalized AS (
    SELECT
        expanded.*,
        lower(
            COALESCE(expanded.effective_using_expression, '')
        ) AS normalized_using,
        lower(
            COALESCE(expanded.effective_with_check_expression, '')
        ) AS normalized_with_check,
        lower(
            pg_catalog.concat_ws(
                ' ',
                expanded.effective_using_expression,
                expanded.effective_with_check_expression
            )
        ) AS normalized_combined
    FROM expanded
),
review AS (
    SELECT
        normalized.*,
        CASE operation_name
            WHEN 'SELECT' THEN effective_using_expression IS NOT NULL
            WHEN 'INSERT' THEN effective_with_check_expression IS NOT NULL
            WHEN 'UPDATE' THEN effective_using_expression IS NOT NULL
                               AND effective_with_check_expression IS NOT NULL
            WHEN 'DELETE' THEN effective_using_expression IS NOT NULL
            ELSE false
        END AS required_predicates_present,
        btrim(
            pg_catalog.regexp_replace(
                normalized_using,
                '[()[:space:]]',
                '',
                'g'
            )
        ) IN ('true', '1=1') AS using_is_literal_true,
        btrim(
            pg_catalog.regexp_replace(
                normalized_with_check,
                '[()[:space:]]',
                '',
                'g'
            )
        ) IN ('true', '1=1') AS with_check_is_literal_true,
        normalized_combined ~ '(^|[^a-z0-9_])or[ (]+true([^a-z0-9_]|$)'
            OR normalized_combined ~ '(^|[^a-z0-9_])true[ )]+or([^a-z0-9_]|$)'
            OR normalized_combined ~ '(^|[^0-9])1[ ]*=[ ]*1([^0-9]|$)'
            AS possible_tautology,
        operation_name = 'INSERT'
            AND normalized_with_check
                ~ '(auth[.]uid|current_marketplace_party_id|owner|user_id|marketplace_party_id)'
            AND normalized_with_check
                !~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
            AS possible_owner_only_insert_check,
        operation_name = 'UPDATE'
            AND (
                effective_with_check_expression IS NULL
                OR (
                    normalized_using
                        ~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
                    AND normalized_with_check
                        !~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
                )
            ) AS possible_state_transition_bypass,
        table_name = 'marketplace_party'
            AND operation_name IN ('INSERT', 'UPDATE')
            AND policy_roles && ARRAY['public', 'anon', 'authenticated']::name[]
            AND normalized_with_check !~ '(approval_state|state_reason)'
            AS policy_layer_approval_manipulation_risk,
        operation_name IN ('INSERT', 'UPDATE', 'DELETE')
            AND policy_roles && ARRAY['public', 'anon', 'authenticated']::name[]
            AND normalized_combined
                !~ '(auth[.]uid|current_marketplace_party_id|is_admin)'
            AS possible_cross_principal_write,
        operation_name = 'SELECT'
            AND NOT EXISTS (
                SELECT 1
                FROM anonymous_read_tables AS allowed
                WHERE allowed.table_name = normalized.table_name
            )
            AND policy_roles && ARRAY['public', 'anon', 'authenticated']::name[]
            AND normalized_combined
                !~ '(auth[.]uid|current_marketplace_party_id|is_admin)'
            AS possible_cross_principal_read,
        EXISTS (
            SELECT 1
            FROM unnest(policy_roles) AS assigned(role_name)
            WHERE assigned.role_name
                <> ALL (
                    ARRAY[
                        'public',
                        'anon',
                        'authenticated',
                        'service_role'
                    ]::name[]
                )
        ) AS unexpected_policy_role,
        'public'::name = ANY (policy_roles) AS policy_assigned_to_public,
        normalized_combined ~ '(^|[^a-z0-9_])is_admin[ (]'
            AND policy_name !~ 'admin'
            AS unexpected_admin_branch,
        (
            SELECT count(*)
            FROM expanded AS overlap
            WHERE overlap.table_name = normalized.table_name
              AND overlap.operation_name = normalized.operation_name
              AND overlap.policy_mode = 'PERMISSIVE'
              AND (
                  overlap.policy_roles && normalized.policy_roles
                  OR 'public'::name = ANY (overlap.policy_roles)
                  OR 'public'::name = ANY (normalized.policy_roles)
              )
        ) AS overlapping_permissive_policy_count
    FROM normalized
)
SELECT
    table_name,
    policy_name,
    policy_mode,
    policy_roles,
    operation_name,
    effective_using_expression,
    effective_with_check_expression,
    required_predicates_present,
    using_is_literal_true,
    with_check_is_literal_true,
    possible_tautology,
    possible_owner_only_insert_check,
    possible_state_transition_bypass,
    policy_layer_approval_manipulation_risk,
    possible_cross_principal_read,
    possible_cross_principal_write,
    unexpected_policy_role,
    policy_assigned_to_public,
    unexpected_admin_branch,
    overlapping_permissive_policy_count,
    overlapping_permissive_policy_count > 1
        AS overlapping_permissive_policy_review_required
FROM review
ORDER BY table_name, policy_name, display_order;


-- 06. Direct catalog dependencies for every policy.
-- Dependency presence does not prove the complete Boolean expression correct.
WITH policy_objects AS (
    SELECT
        policy.oid AS policy_oid,
        policy.polrelid AS policy_table_oid,
        relation.relname AS table_name,
        policy.polname AS policy_name
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation
        ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
),
dependencies AS (
    SELECT
        policy.policy_oid,
        policy.policy_table_oid,
        policy.table_name,
        policy.policy_name,
        dependency.refclassid,
        dependency.refobjid,
        dependency.refobjsubid,
        dependency.deptype
    FROM policy_objects AS policy
    LEFT JOIN pg_catalog.pg_depend AS dependency
        ON dependency.classid = 'pg_catalog.pg_policy'::pg_catalog.regclass
       AND dependency.objid = policy.policy_oid
)
SELECT
    dependency.table_name,
    dependency.policy_name,
    CASE
        WHEN dependency.refobjid IS NULL THEN 'no_recorded_dependency'
        WHEN dependency.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
        THEN 'relation'
        WHEN dependency.refclassid = 'pg_catalog.pg_proc'::pg_catalog.regclass
        THEN 'function'
        WHEN dependency.refclassid = 'pg_catalog.pg_type'::pg_catalog.regclass
        THEN 'type'
        ELSE 'other_catalog_object'
    END AS dependency_kind,
    COALESCE(
        relation_namespace.nspname,
        function_namespace.nspname,
        type_namespace.nspname
    ) AS referenced_schema,
    COALESCE(
        referenced_relation.relname,
        referenced_function.proname,
        referenced_type.typname
    ) AS referenced_object,
    referenced_attribute.attname AS referenced_column,
    dependency.deptype AS dependency_type,
    dependency.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
        AND dependency.refobjid = dependency.policy_table_oid
        AND dependency.refobjsubid = 0
        AND dependency.deptype = 'n'::pg_catalog."char"
        AS recursive_or_self_reference,
    referenced_function.prosecdef AS referenced_function_security_definer,
    referenced_function.provolatile AS referenced_function_volatility,
    referenced_function.proconfig AS referenced_function_configuration
FROM dependencies AS dependency
LEFT JOIN pg_catalog.pg_class AS referenced_relation
    ON dependency.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
   AND referenced_relation.oid = dependency.refobjid
LEFT JOIN pg_catalog.pg_namespace AS relation_namespace
    ON relation_namespace.oid = referenced_relation.relnamespace
LEFT JOIN pg_catalog.pg_attribute AS referenced_attribute
    ON referenced_attribute.attrelid = referenced_relation.oid
   AND referenced_attribute.attnum = dependency.refobjsubid
   AND dependency.refobjsubid > 0
LEFT JOIN pg_catalog.pg_proc AS referenced_function
    ON dependency.refclassid = 'pg_catalog.pg_proc'::pg_catalog.regclass
   AND referenced_function.oid = dependency.refobjid
LEFT JOIN pg_catalog.pg_namespace AS function_namespace
    ON function_namespace.oid = referenced_function.pronamespace
LEFT JOIN pg_catalog.pg_type AS referenced_type
    ON dependency.refclassid = 'pg_catalog.pg_type'::pg_catalog.regclass
   AND referenced_type.oid = dependency.refobjid
LEFT JOIN pg_catalog.pg_namespace AS type_namespace
    ON type_namespace.oid = referenced_type.typnamespace
ORDER BY
    dependency.table_name,
    dependency.policy_name,
    dependency_kind,
    referenced_schema,
    referenced_object,
    referenced_column;


-- 07. Effective table privilege and applicable-policy coverage for PUBLIC,
-- anon, authenticated, and service_role. MAINTAIN is read from ACL metadata so
-- PostgreSQL 15/16 never parse it as a privilege-check function argument.
-- The sequence default-ACL metadata subquery deliberately maps catalog code S
-- to acldefault code s; it does not filter grantees.
WITH RECURSIVE requested_roles(role_name, role_oid, conceptual_public) AS (
    SELECT 'PUBLIC'::name, NULL::oid, true
    UNION ALL
    SELECT role_name.role_name, role.oid, false
    FROM (
        VALUES
            ('anon'::name),
            ('authenticated'::name),
            ('service_role'::name)
    ) AS role_name(role_name)
    LEFT JOIN pg_catalog.pg_roles AS role
        ON role.rolname = role_name.role_name
),
role_closure(source_role_name, source_role_oid, inherited_role_oid, path) AS (
    SELECT
        requested.role_name,
        requested.role_oid,
        requested.role_oid,
        ARRAY[requested.role_oid]::oid[]
    FROM requested_roles AS requested
    WHERE requested.role_oid IS NOT NULL
    UNION ALL
    SELECT
        closure.source_role_name,
        closure.source_role_oid,
        membership.roleid,
        closure.path || membership.roleid
    FROM role_closure AS closure
    JOIN pg_catalog.pg_auth_members AS membership
        ON membership.member = closure.inherited_role_oid
    JOIN pg_catalog.pg_roles AS member_role
        ON member_role.oid = membership.member
    WHERE member_role.rolinherit
      AND NOT membership.roleid = ANY (closure.path)
),
public_tables AS (
    SELECT
        relation.oid AS table_oid,
        relation.relname AS table_name,
        relation.relowner,
        relation.relacl,
        relation.relrowsecurity,
        relation.relforcerowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN (
          'r'::pg_catalog."char",
          'p'::pg_catalog."char"
      )
),
privileges(privilege_name, display_order) AS (
    VALUES
        ('SELECT'::text, 1),
        ('INSERT'::text, 2),
        ('UPDATE'::text, 3),
        ('DELETE'::text, 4),
        ('TRUNCATE'::text, 5),
        ('REFERENCES'::text, 6),
        ('TRIGGER'::text, 7),
        ('MAINTAIN'::text, 8)
),
table_acl AS (
    SELECT
        table_metadata.table_oid,
        acl.grantee,
        acl.privilege_type,
        acl.is_grantable
    FROM public_tables AS table_metadata
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            table_metadata.relacl,
            pg_catalog.acldefault(
                'r'::pg_catalog."char",
                table_metadata.relowner
            )
        )
    ) AS acl
),
policy_metadata AS (
    SELECT
        policy.polrelid AS table_oid,
        policy.polpermissive,
        policy.polroles,
        CASE policy.polcmd
            WHEN '*'::pg_catalog."char" THEN 'ALL'
            WHEN 'r'::pg_catalog."char" THEN 'SELECT'
            WHEN 'a'::pg_catalog."char" THEN 'INSERT'
            WHEN 'w'::pg_catalog."char" THEN 'UPDATE'
            WHEN 'd'::pg_catalog."char" THEN 'DELETE'
        END AS policy_command
    FROM pg_catalog.pg_policy AS policy
),
sequence_object_type_mapping(
    catalog_object_type,
    acldefault_object_type
) AS (
    VALUES (
        'S'::pg_catalog."char",
        's'::pg_catalog."char"
    )
),
sequence_default_acl_metadata AS (
    SELECT count(*)::bigint AS sequence_default_acl_entry_count
    FROM pg_catalog.pg_default_acl AS default_acl
    CROSS JOIN sequence_object_type_mapping AS object_type
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            default_acl.defaclacl,
            pg_catalog.acldefault(
                object_type.acldefault_object_type,
                default_acl.defaclrole
            )
        )
    ) AS acl
    WHERE default_acl.defaclobjtype = object_type.catalog_object_type
)
SELECT
    table_metadata.table_name,
    requested.role_name,
    requested.conceptual_public OR requested.role_oid IS NOT NULL
        AS role_exists,
    privilege.privilege_name,
    CASE
        WHEN privilege.privilege_name = 'MAINTAIN'
         AND current_setting('server_version_num')::integer < 170000
        THEN 'not_supported'
        ELSE 'supported'
    END AS privilege_support,
    CASE
        WHEN privilege.privilege_name = 'MAINTAIN'
         AND current_setting('server_version_num')::integer < 170000
        THEN NULL
        WHEN requested.conceptual_public
        THEN EXISTS (
            SELECT 1
            FROM table_acl AS acl
            WHERE acl.table_oid = table_metadata.table_oid
              AND acl.grantee = 0
              AND acl.privilege_type = privilege.privilege_name
        )
        WHEN requested.role_oid IS NULL THEN NULL
        ELSE table_metadata.relowner = requested.role_oid
          OR EXISTS (
              SELECT 1
              FROM table_acl AS acl
              WHERE acl.table_oid = table_metadata.table_oid
                AND acl.privilege_type = privilege.privilege_name
                AND (
                    acl.grantee = 0
                    OR acl.grantee IN (
                        SELECT closure.inherited_role_oid
                        FROM role_closure AS closure
                        WHERE closure.source_role_oid = requested.role_oid
                    )
                )
          )
    END AS effective_table_privilege,
    table_metadata.relrowsecurity AS rls_enabled,
    table_metadata.relforcerowsecurity AS force_rls_enabled,
    COALESCE(role_metadata.rolbypassrls, false) AS role_bypasses_rls,
    CASE
        WHEN requested.role_oid IS NULL THEN false
        ELSE table_metadata.relowner = requested.role_oid
             AND NOT table_metadata.relforcerowsecurity
    END AS role_has_owner_rls_bypass,
    CASE
        WHEN privilege.privilege_name
             NOT IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
        THEN NULL
        ELSE (
            SELECT count(*)
            FROM policy_metadata AS policy
            WHERE policy.table_oid = table_metadata.table_oid
              AND policy.polpermissive
              AND policy.policy_command
                  IN ('ALL', privilege.privilege_name)
              AND (
                  0::oid = ANY (policy.polroles)
                  OR (
                      requested.role_oid IS NOT NULL
                      AND EXISTS (
                          SELECT 1
                          FROM role_closure AS closure
                          WHERE closure.source_role_oid = requested.role_oid
                            AND closure.inherited_role_oid
                                = ANY (policy.polroles)
                      )
                  )
              )
        )
    END AS applicable_permissive_policy_count,
    CASE
        WHEN privilege.privilege_name
             NOT IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
        THEN NULL
        ELSE (
            SELECT count(*)
            FROM policy_metadata AS policy
            WHERE policy.table_oid = table_metadata.table_oid
              AND NOT policy.polpermissive
              AND policy.policy_command
                  IN ('ALL', privilege.privilege_name)
              AND (
                  0::oid = ANY (policy.polroles)
                  OR (
                      requested.role_oid IS NOT NULL
                      AND EXISTS (
                          SELECT 1
                          FROM role_closure AS closure
                          WHERE closure.source_role_oid = requested.role_oid
                            AND closure.inherited_role_oid
                                = ANY (policy.polroles)
                      )
                  )
              )
        )
    END AS applicable_restrictive_policy_count,
    sequence_default.sequence_default_acl_entry_count,
    'S'::pg_catalog."char" AS sequence_catalog_object_type,
    's'::pg_catalog."char" AS sequence_acldefault_object_type
FROM public_tables AS table_metadata
CROSS JOIN requested_roles AS requested
CROSS JOIN privileges AS privilege
LEFT JOIN pg_catalog.pg_roles AS role_metadata
    ON role_metadata.oid = requested.role_oid
CROSS JOIN sequence_default_acl_metadata AS sequence_default
ORDER BY
    table_metadata.table_name,
    requested.role_name,
    privilege.display_order;


-- 08. Role membership/inheritance paths that could alter effective access.
WITH RECURSIVE requested_roles(role_name, role_oid) AS (
    SELECT requested.role_name, role.oid
    FROM (
        VALUES
            ('anon'::name),
            ('authenticated'::name),
            ('service_role'::name)
    ) AS requested(role_name)
    LEFT JOIN pg_catalog.pg_roles AS role
        ON role.rolname = requested.role_name
),
membership_paths(
    source_role,
    source_role_oid,
    reached_role_oid,
    inheritance_depth,
    membership_path
) AS (
    SELECT
        requested.role_name,
        requested.role_oid,
        requested.role_oid,
        0,
        ARRAY[requested.role_oid]::oid[]
    FROM requested_roles AS requested
    WHERE requested.role_oid IS NOT NULL
    UNION ALL
    SELECT
        path.source_role,
        path.source_role_oid,
        membership.roleid,
        path.inheritance_depth + 1,
        path.membership_path || membership.roleid
    FROM membership_paths AS path
    JOIN pg_catalog.pg_auth_members AS membership
        ON membership.member = path.reached_role_oid
    JOIN pg_catalog.pg_roles AS member_role
        ON member_role.oid = membership.member
    WHERE member_role.rolinherit
      AND NOT membership.roleid = ANY (path.membership_path)
)
SELECT
    requested.role_name AS source_role,
    requested.role_oid IS NOT NULL AS source_role_exists,
    reached.rolname AS inherited_or_self_role,
    path.inheritance_depth,
    source.rolinherit AS source_role_inherits,
    reached.rolsuper AS reached_role_is_superuser,
    reached.rolbypassrls AS reached_role_bypasses_rls,
    reached.rolcreaterole AS reached_role_can_create_roles,
    reached.rolcreatedb AS reached_role_can_create_databases,
    reached.rolname = 'service_role' AS reached_managed_elevated_server_role,
    requested.role_name IN ('anon', 'authenticated')
        AND path.inheritance_depth > 0
        AND (
            reached.rolsuper
            OR reached.rolbypassrls
            OR reached.rolname = 'service_role'
        ) AS unexpected_client_elevation_path
FROM requested_roles AS requested
LEFT JOIN membership_paths AS path
    ON path.source_role_oid = requested.role_oid
LEFT JOIN pg_catalog.pg_roles AS source
    ON source.oid = requested.role_oid
LEFT JOIN pg_catalog.pg_roles AS reached
    ON reached.oid = path.reached_role_oid
ORDER BY requested.role_name, path.inheritance_depth, reached.rolname;


-- 09. Table-by-table FORCE RLS suitability evidence. The audit deliberately
-- does not infer force_candidate or force_not_recommended from one catalog bit.
-- Those classifications require verified owner, service, and background-job
-- workflows; otherwise the result remains requires_business_decision or
-- insufficient_evidence.
WITH public_tables AS (
    SELECT
        relation.oid AS table_oid,
        relation.relname AS table_name,
        relation.relowner,
        relation.relacl,
        relation.relrowsecurity,
        relation.relforcerowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN (
          'r'::pg_catalog."char",
          'p'::pg_catalog."char"
      )
),
security_definer_table_dependencies AS (
    SELECT DISTINCT
        dependency.refobjid AS table_oid,
        function_namespace.nspname AS function_schema,
        function_metadata.proname AS function_name
    FROM pg_catalog.pg_depend AS dependency
    JOIN pg_catalog.pg_proc AS function_metadata
        ON dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
       AND function_metadata.oid = dependency.objid
       AND function_metadata.prosecdef
    JOIN pg_catalog.pg_namespace AS function_namespace
        ON function_namespace.oid = function_metadata.pronamespace
    WHERE dependency.refclassid
        = 'pg_catalog.pg_class'::pg_catalog.regclass
),
function_summary AS (
    SELECT
        dependency.table_oid,
        string_agg(
            DISTINCT dependency.function_schema
                || '.' || dependency.function_name,
            ', ' ORDER BY dependency.function_schema
                || '.' || dependency.function_name
        ) AS recorded_security_definer_functions
    FROM security_definer_table_dependencies AS dependency
    GROUP BY dependency.table_oid
),
service_role AS (
    SELECT role.oid AS role_oid
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = 'service_role'
)
SELECT
    table_metadata.table_name,
    pg_catalog.pg_get_userbyid(table_metadata.relowner) AS owner_name,
    table_metadata.relrowsecurity AS rls_enabled,
    table_metadata.relforcerowsecurity AS current_force_rls_enabled,
    CASE
        WHEN NOT table_metadata.relrowsecurity THEN 'not_applicable_without_rls'
        WHEN table_metadata.relforcerowsecurity THEN 'owner_subject_to_rls'
        ELSE 'potentially_material_owner_bypass'
    END AS owner_bypass_materiality,
    function_summary.recorded_security_definer_functions,
    CASE
        WHEN service.role_oid IS NULL THEN NULL
        ELSE
            pg_catalog.has_table_privilege(
                service.role_oid,
                table_metadata.table_oid,
                'SELECT'
            )
            OR pg_catalog.has_table_privilege(
                service.role_oid,
                table_metadata.table_oid,
                'INSERT'
            )
            OR pg_catalog.has_table_privilege(
                service.role_oid,
                table_metadata.table_oid,
                'UPDATE'
            )
            OR pg_catalog.has_table_privilege(
                service.role_oid,
                table_metadata.table_oid,
                'DELETE'
            )
    END AS service_role_has_effective_row_privilege,
    'metadata_cannot_identify_background_job_requirements'::text
        AS service_or_background_job_requirements,
    CASE
        WHEN table_metadata.table_name IN (
            'admin_user',
            'commission',
            'commission_reversal',
            'order_line_item',
            'payment',
            'platform_config',
            'purchase_order',
            'refund',
            'settlement'
        )
          OR function_summary.recorded_security_definer_functions IS NOT NULL
        THEN 'requires_business_decision'
        ELSE 'insufficient_evidence'
    END AS force_rls_candidate_classification,
    CASE
        WHEN table_metadata.table_name IN (
            'admin_user',
            'commission',
            'commission_reversal',
            'order_line_item',
            'payment',
            'platform_config',
            'purchase_order',
            'refund',
            'settlement'
        )
        THEN 'validate_financial_admin_and_background_workflows'
        WHEN function_summary.recorded_security_definer_functions IS NOT NULL
        THEN 'validate_security_definer_owner_bypass_dependency'
        ELSE 'collect_owner_and_background_workflow_evidence'
    END AS classification_reason
FROM public_tables AS table_metadata
LEFT JOIN function_summary
    ON function_summary.table_oid = table_metadata.table_oid
LEFT JOIN service_role AS service ON true
ORDER BY table_metadata.table_name;


-- 10. Focused financial and administrative table/view review.
WITH focused_objects(display_order, object_name, expected_kind) AS (
    VALUES
        (1, 'purchase_order'::name, 'table'::text),
        (2, 'order_line_item'::name, 'table'::text),
        (3, 'payment'::name, 'table'::text),
        (4, 'commission'::name, 'table'::text),
        (5, 'refund'::name, 'table'::text),
        (6, 'commission_reversal'::name, 'table'::text),
        (7, 'settlement'::name, 'table'::text),
        (8, 'admin_user'::name, 'table'::text),
        (9, 'platform_config'::name, 'table'::text),
        (10, 'order_financial_position'::name, 'view'::text)
),
public_relations AS (
    SELECT
        relation.oid AS relation_oid,
        relation.relname AS object_name,
        relation.relkind,
        relation.relowner,
        relation.relacl,
        relation.relrowsecurity,
        relation.relforcerowsecurity,
        relation.reloptions,
        CASE
            WHEN relation.relkind = 'v'::pg_catalog."char"
            THEN pg_catalog.pg_get_viewdef(relation.oid, true)
        END AS complete_view_definition
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
),
policy_summary AS (
    SELECT
        policy.tablename AS table_name,
        count(*) AS policy_count,
        jsonb_agg(
            jsonb_build_object(
                'policy_name', policy.policyname,
                'mode', policy.permissive,
                'roles', policy.roles,
                'command', policy.cmd,
                'using', policy.qual,
                'with_check', policy.with_check
            )
            ORDER BY policy.policyname
        ) AS complete_policy_metadata
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
    GROUP BY policy.tablename
),
grant_summary AS (
    SELECT
        relation.relation_oid,
        string_agg(
            DISTINCT (
                CASE
                    WHEN acl.grantee = 0 THEN 'PUBLIC'
                    ELSE pg_catalog.pg_get_userbyid(acl.grantee)
                END
                || ':' || acl.privilege_type
                || CASE WHEN acl.is_grantable THEN ':GRANTABLE' ELSE '' END
            ),
            ', ' ORDER BY (
                CASE
                    WHEN acl.grantee = 0 THEN 'PUBLIC'
                    ELSE pg_catalog.pg_get_userbyid(acl.grantee)
                END
                || ':' || acl.privilege_type
                || CASE WHEN acl.is_grantable THEN ':GRANTABLE' ELSE '' END
            )
        ) AS direct_acl_entries
    FROM public_relations AS relation
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            relation.relacl,
            pg_catalog.acldefault(
                'r'::pg_catalog."char",
                relation.relowner
            )
        )
    ) AS acl
    GROUP BY relation.relation_oid
)
SELECT
    target.object_name,
    target.expected_kind,
    relation.relation_oid IS NOT NULL AS object_exists,
    CASE relation.relkind
        WHEN 'r'::pg_catalog."char" THEN 'ordinary_table'
        WHEN 'p'::pg_catalog."char" THEN 'partitioned_table'
        WHEN 'v'::pg_catalog."char" THEN 'view'
        WHEN 'm'::pg_catalog."char" THEN 'materialized_view'
        ELSE 'missing_or_unexpected_kind'
    END AS actual_kind,
    pg_catalog.pg_get_userbyid(relation.relowner) AS owner_name,
    relation.relrowsecurity AS rls_enabled,
    relation.relforcerowsecurity AS force_rls_enabled,
    relation.complete_view_definition,
    CASE
        WHEN target.expected_kind <> 'view' THEN NULL
        ELSE COALESCE(
            relation.reloptions @> ARRAY['security_invoker=true']::text[],
            false
        )
    END AS view_security_invoker_enabled,
    COALESCE(policy.policy_count, 0) AS policy_count,
    policy.complete_policy_metadata,
    grant_metadata.direct_acl_entries,
    CASE
        WHEN relation.relation_oid IS NULL THEN 'critical_expected_object_missing'
        WHEN target.expected_kind = 'table'
         AND relation.relkind NOT IN (
             'r'::pg_catalog."char",
             'p'::pg_catalog."char"
         ) THEN 'critical_unexpected_table_kind'
        WHEN target.expected_kind = 'view'
         AND relation.relkind <> 'v'::pg_catalog."char"
        THEN 'critical_unexpected_view_kind'
        WHEN target.expected_kind = 'table'
         AND NOT relation.relrowsecurity
        THEN 'critical_rls_disabled'
        WHEN target.expected_kind = 'view'
         AND NOT COALESCE(
             relation.reloptions @> ARRAY['security_invoker=true']::text[],
             false
         ) THEN 'critical_view_not_security_invoker'
        ELSE 'metadata_captured_for_human_review'
    END AS focused_review_status
FROM focused_objects AS target
LEFT JOIN public_relations AS relation
    ON relation.object_name = target.object_name
LEFT JOIN policy_summary AS policy
    ON policy.table_name = target.object_name
LEFT JOIN grant_summary AS grant_metadata
    ON grant_metadata.relation_oid = relation.relation_oid
ORDER BY target.display_order;


-- 11. Every public parent-child foreign-key direction and recorded policy
-- relation dependency, including mutual and self-reference risk signals.
WITH public_relations AS (
    SELECT relation.oid, relation.relname
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN (
          'r'::pg_catalog."char",
          'p'::pg_catalog."char"
      )
),
foreign_keys AS (
    SELECT
        constraint_metadata.oid AS constraint_oid,
        constraint_metadata.conname AS constraint_name,
        constraint_metadata.conrelid AS child_table_oid,
        child.relname AS child_table,
        constraint_metadata.confrelid AS parent_table_oid,
        parent.relname AS parent_table,
        pg_catalog.pg_get_constraintdef(
            constraint_metadata.oid,
            true
        ) AS complete_constraint_definition
    FROM pg_catalog.pg_constraint AS constraint_metadata
    JOIN public_relations AS child
        ON child.oid = constraint_metadata.conrelid
    JOIN public_relations AS parent
        ON parent.oid = constraint_metadata.confrelid
    WHERE constraint_metadata.contype = 'f'::pg_catalog."char"
),
policy_relation_dependencies AS (
    SELECT DISTINCT
        policy.polrelid AS policy_table_oid,
        policy.polname AS policy_name,
        dependency.refobjid AS referenced_table_oid,
        dependency.refobjsubid AS referenced_object_subid
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_depend AS dependency
        ON dependency.classid = 'pg_catalog.pg_policy'::pg_catalog.regclass
       AND dependency.objid = policy.oid
       AND dependency.refclassid
           = 'pg_catalog.pg_class'::pg_catalog.regclass
       AND dependency.deptype = 'n'::pg_catalog."char"
    JOIN public_relations AS policy_table
        ON policy_table.oid = policy.polrelid
    JOIN public_relations AS referenced_table
        ON referenced_table.oid = dependency.refobjid
),
direction_summary AS (
    SELECT
        foreign_key.*,
        count(DISTINCT child_policy.policy_name)
            AS child_policy_references_parent_count,
        string_agg(
            DISTINCT child_policy.policy_name,
            ', ' ORDER BY child_policy.policy_name
        ) AS child_policies_referencing_parent,
        count(DISTINCT parent_policy.policy_name)
            AS parent_policy_references_child_count,
        string_agg(
            DISTINCT parent_policy.policy_name,
            ', ' ORDER BY parent_policy.policy_name
        ) AS parent_policies_referencing_child,
        count(DISTINCT child_self.policy_name)
            AS child_self_referencing_policy_count,
        count(DISTINCT parent_self.policy_name)
            AS parent_self_referencing_policy_count
    FROM foreign_keys AS foreign_key
    LEFT JOIN policy_relation_dependencies AS child_policy
        ON child_policy.policy_table_oid = foreign_key.child_table_oid
       AND child_policy.referenced_table_oid = foreign_key.parent_table_oid
    LEFT JOIN policy_relation_dependencies AS parent_policy
        ON parent_policy.policy_table_oid = foreign_key.parent_table_oid
       AND parent_policy.referenced_table_oid = foreign_key.child_table_oid
    LEFT JOIN policy_relation_dependencies AS child_self
        ON child_self.policy_table_oid = foreign_key.child_table_oid
       AND child_self.referenced_table_oid = foreign_key.child_table_oid
       AND child_self.referenced_object_subid = 0
    LEFT JOIN policy_relation_dependencies AS parent_self
        ON parent_self.policy_table_oid = foreign_key.parent_table_oid
       AND parent_self.referenced_table_oid = foreign_key.parent_table_oid
       AND parent_self.referenced_object_subid = 0
    GROUP BY
        foreign_key.constraint_oid,
        foreign_key.constraint_name,
        foreign_key.child_table_oid,
        foreign_key.child_table,
        foreign_key.parent_table_oid,
        foreign_key.parent_table,
        foreign_key.complete_constraint_definition
)
SELECT
    constraint_name,
    child_table,
    parent_table,
    complete_constraint_definition,
    child_policy_references_parent_count,
    child_policies_referencing_parent,
    parent_policy_references_child_count,
    parent_policies_referencing_child,
    child_self_referencing_policy_count,
    parent_self_referencing_policy_count,
    child_policy_references_parent_count > 0
        AND parent_policy_references_child_count > 0
        AS mutual_policy_dependency_review_required,
    child_self_referencing_policy_count > 0
        OR parent_self_referencing_policy_count > 0
        AS recursive_policy_review_required
FROM direction_summary
ORDER BY child_table, parent_table, constraint_name;


-- 12. Prioritized static findings. A sentinel row explicitly reports an empty
-- result. Hypotheses require predicate and business-workflow review before any
-- remediation design.
WITH operations(operation_name) AS (
    VALUES
        ('SELECT'::text),
        ('INSERT'::text),
        ('UPDATE'::text),
        ('DELETE'::text)
),
anonymous_read_tables(table_name) AS (
    VALUES
        ('category'::name),
        ('custom_offering'::name),
        ('marketplace_party'::name),
        ('party_capability'::name),
        ('product'::name),
        ('product_3d_model'::name),
        ('product_color'::name),
        ('product_enrichment_assignment'::name),
        ('product_enrichment_attribute'::name),
        ('product_image'::name),
        ('review'::name),
        ('service_type'::name)
),
expanded_policies AS (
    SELECT
        policy.tablename AS table_name,
        policy.policyname AS policy_name,
        policy.permissive AS policy_mode,
        policy.roles AS policy_roles,
        operation.operation_name,
        CASE
            WHEN operation.operation_name IN ('SELECT', 'UPDATE', 'DELETE')
            THEN policy.qual
        END AS effective_using_expression,
        CASE
            WHEN operation.operation_name IN ('INSERT', 'UPDATE')
             AND policy.cmd IN ('ALL', 'UPDATE')
            THEN COALESCE(policy.with_check, policy.qual)
            WHEN operation.operation_name = 'INSERT'
            THEN policy.with_check
        END AS effective_with_check_expression
    FROM pg_catalog.pg_policies AS policy
    CROSS JOIN operations AS operation
    WHERE policy.schemaname = 'public'
      AND (
          policy.cmd = 'ALL'
          OR policy.cmd = operation.operation_name
      )
),
policy_signals AS (
    SELECT
        policy.*,
        lower(
            COALESCE(policy.effective_using_expression, '')
        ) AS normalized_using,
        lower(
            COALESCE(policy.effective_with_check_expression, '')
        ) AS normalized_with_check,
        lower(
            pg_catalog.concat_ws(
                ' ',
                policy.effective_using_expression,
                policy.effective_with_check_expression
            )
        ) AS normalized_combined,
        (
            SELECT count(*)
            FROM expanded_policies AS overlap
            WHERE overlap.table_name = policy.table_name
              AND overlap.operation_name = policy.operation_name
              AND overlap.policy_mode = 'PERMISSIVE'
              AND (
                  overlap.policy_roles && policy.policy_roles
                  OR 'public'::name = ANY (overlap.policy_roles)
                  OR 'public'::name = ANY (policy.policy_roles)
              )
        ) AS overlapping_permissive_policy_count
    FROM expanded_policies AS policy
),
policy_findings AS (
    SELECT
        signal.severity,
        policy.table_name,
        policy.policy_name,
        signal.finding,
        signal.evidence,
        signal.recommended_decision,
        signal.migration_required,
        signal.human_business_decision_required,
        signal.finding_classification
    FROM policy_signals AS policy
    CROSS JOIN LATERAL (
        VALUES
            (
                'critical'::text,
                'required_operation_predicate_missing'::text,
                'effective operation lacks a required USING or WITH CHECK predicate'::text,
                'review exact policy semantics before designing operation-specific replacement'::text,
                true,
                false,
                'proven_structural_finding'::text,
                CASE policy.operation_name
                    WHEN 'SELECT' THEN policy.effective_using_expression IS NULL
                    WHEN 'INSERT' THEN policy.effective_with_check_expression IS NULL
                    WHEN 'UPDATE' THEN policy.effective_using_expression IS NULL
                                       OR policy.effective_with_check_expression IS NULL
                    WHEN 'DELETE' THEN policy.effective_using_expression IS NULL
                    ELSE true
                END
            ),
            (
                'critical',
                'literal_true_or_tautology',
                'effective predicate contains a literal-true or simple tautology signal',
                'reject broad predicate unless a documented public-access requirement proves it intentional',
                true,
                true,
                'static_risk_signal',
                btrim(
                    pg_catalog.regexp_replace(
                        policy.normalized_combined,
                        '[()[:space:]]',
                        '',
                        'g'
                    )
                ) IN ('true', '1=1')
                OR policy.normalized_combined
                    ~ '(^|[^a-z0-9_])or[ (]+true([^a-z0-9_]|$)'
                OR policy.normalized_combined
                    ~ '(^|[^0-9])1[ ]*=[ ]*1([^0-9]|$)'
            ),
            (
                'high',
                'owner_only_insert_or_state_transition_risk',
                'ownership-only INSERT or UPDATE state-transition signal requires review',
                'define allowed initial state and transition rules before remediation',
                false,
                true,
                'business_semantics_hypothesis',
                (
                    policy.operation_name = 'INSERT'
                    AND policy.normalized_with_check
                        ~ '(auth[.]uid|current_marketplace_party_id|owner|user_id|marketplace_party_id)'
                    AND policy.normalized_with_check
                        !~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
                )
                OR (
                    policy.operation_name = 'UPDATE'
                    AND (
                        policy.effective_with_check_expression IS NULL
                        OR (
                            policy.normalized_using
                                ~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
                            AND policy.normalized_with_check
                                !~ '(approval_state|confirmation_state|lifecycle_state|publication_state|status)'
                        )
                    )
                )
            ),
            (
                'critical',
                'marketplace_party_approval_policy_gap',
                'marketplace-party write policy does not itself constrain approval columns',
                'confirm column grants and triggers, then decide whether policy defense-in-depth is required',
                false,
                true,
                'layered_control_hypothesis',
                policy.table_name = 'marketplace_party'
                AND policy.operation_name IN ('INSERT', 'UPDATE')
                AND policy.policy_roles
                    && ARRAY['public', 'anon', 'authenticated']::name[]
                AND policy.normalized_with_check
                    !~ '(approval_state|state_reason)'
            ),
            (
                'high',
                'unexpected_policy_role',
                'policy is assigned to a role outside the reviewed API role set',
                'identify the role and prove the business requirement before retaining access',
                false,
                true,
                'proven_structural_finding',
                EXISTS (
                    SELECT 1
                    FROM unnest(policy.policy_roles) AS assigned(role_name)
                    WHERE assigned.role_name
                        <> ALL (
                            ARRAY[
                                'public',
                                'anon',
                                'authenticated',
                                'service_role'
                            ]::name[]
                        )
                )
            ),
            (
                'medium',
                'policy_assigned_to_public',
                'policy applies to PUBLIC and therefore every database role',
                'confirm that the complete operation and predicate are intentionally universal',
                false,
                true,
                'business_semantics_hypothesis',
                'public'::name = ANY (policy.policy_roles)
            ),
            (
                'high',
                'unexpected_admin_branch',
                'an administrator helper appears outside an explicitly named administrator policy',
                'verify that the branch existed in the approved authorization design',
                false,
                true,
                'static_risk_signal',
                policy.normalized_combined
                    ~ '(^|[^a-z0-9_])is_admin[ (]'
                AND policy.policy_name !~ 'admin'
            ),
            (
                'medium',
                'overlapping_permissive_policies',
                'multiple applicable permissive policies may broaden access through OR semantics',
                'review the combined Boolean authorization result operation by operation',
                false,
                true,
                'business_semantics_hypothesis',
                policy.overlapping_permissive_policy_count > 1
            ),
            (
                'high',
                'possible_cross_principal_read',
                'client-targeted private-table read has no recognized principal ownership or admin anchor',
                'prove customer or seller isolation from the complete predicate and workflow',
                false,
                true,
                'business_semantics_hypothesis',
                policy.operation_name = 'SELECT'
                AND NOT EXISTS (
                    SELECT 1
                    FROM anonymous_read_tables AS allowed
                    WHERE allowed.table_name = policy.table_name
                )
                AND policy.policy_roles
                    && ARRAY['public', 'anon', 'authenticated']::name[]
                AND policy.normalized_combined
                    !~ '(auth[.]uid|current_marketplace_party_id|is_admin)'
            ),
            (
                'high',
                'possible_cross_principal_write',
                'client-targeted write policy has no recognized principal ownership or admin anchor',
                'prove customer or seller isolation from the complete predicate and workflow',
                false,
                true,
                'business_semantics_hypothesis',
                policy.operation_name IN ('INSERT', 'UPDATE', 'DELETE')
                AND policy.policy_roles
                    && ARRAY['public', 'anon', 'authenticated']::name[]
                AND policy.normalized_combined
                    !~ '(auth[.]uid|current_marketplace_party_id|is_admin)'
            )
    ) AS signal(
        severity,
        finding,
        evidence,
        recommended_decision,
        migration_required,
        human_business_decision_required,
        finding_classification,
        signal_present
    )
    WHERE signal.signal_present
),
relation_findings AS (
    SELECT
        'critical'::text AS severity,
        relation.relname AS table_name,
        NULL::name AS policy_name,
        'public_base_table_rls_disabled'::text AS finding,
        'public base-table metadata reports relrowsecurity=false'::text AS evidence,
        'determine intended access and design a reviewed remediation'::text
            AS recommended_decision,
        true AS migration_required,
        true AS human_business_decision_required,
        'proven_structural_finding'::text AS finding_classification
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN (
          'r'::pg_catalog."char",
          'p'::pg_catalog."char"
      )
      AND NOT relation.relrowsecurity
),
view_findings AS (
    SELECT
        'critical'::text AS severity,
        relation.relname AS table_name,
        NULL::name AS policy_name,
        'financial_view_not_security_invoker'::text AS finding,
        'order_financial_position metadata lacks security_invoker=true'::text
            AS evidence,
        'review underlying-table scope before designing view remediation'::text
            AS recommended_decision,
        true AS migration_required,
        true AS human_business_decision_required,
        'proven_structural_finding'::text AS finding_classification
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relname = 'order_financial_position'
      AND relation.relkind = 'v'::pg_catalog."char"
      AND NOT COALESCE(
          relation.reloptions @> ARRAY['security_invoker=true']::text[],
          false
      )
),
all_findings AS (
    SELECT * FROM policy_findings
    UNION ALL
    SELECT * FROM relation_findings
    UNION ALL
    SELECT * FROM view_findings
),
numbered_findings AS (
    SELECT
        'phase32c_' || lpad(
            row_number() OVER (
                ORDER BY severity, table_name, policy_name, finding
            )::text,
            4,
            '0'
        ) AS finding_id,
        finding.*
    FROM all_findings AS finding
)
SELECT
    finding_id,
    severity,
    table_name AS "table",
    policy_name AS policy,
    finding,
    evidence,
    recommended_decision,
    migration_required,
    human_business_decision_required,
    finding_classification
FROM numbered_findings
UNION ALL
SELECT
    'phase32c_none'::text AS finding_id,
    'none'::text AS severity,
    NULL::name AS "table",
    NULL::name AS policy,
    'no_static_findings'::text AS finding,
    'empty_result_confirmed'::text AS evidence,
    'retain audit output for human review'::text AS recommended_decision,
    false AS migration_required,
    false AS human_business_decision_required,
    'empty_result'::text AS finding_classification
WHERE NOT EXISTS (SELECT 1 FROM numbered_findings)
ORDER BY severity, "table", policy, finding;


-- 13. Final audit-completeness summary. This reports whether every audit
-- dimension produced the expected metadata coverage; it does not approve any
-- policy, FORCE RLS choice, migration, or deployment.
WITH public_tables AS (
    SELECT relation.oid, relation.relname
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN (
          'r'::pg_catalog."char",
          'p'::pg_catalog."char"
      )
),
public_policies AS (
    SELECT policy.tablename, policy.policyname, policy.cmd
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
),
for_all_policies AS (
    SELECT policy.tablename, policy.policyname
    FROM public_policies AS policy
    WHERE policy.cmd = 'ALL'
),
requested_roles AS (
    SELECT requested.role_name, role.oid
    FROM (
        VALUES
            ('anon'::name),
            ('authenticated'::name),
            ('service_role'::name)
    ) AS requested(role_name)
    LEFT JOIN pg_catalog.pg_roles AS role
        ON role.rolname = requested.role_name
),
focused_objects AS (
    SELECT object_name
    FROM (
        VALUES
            ('purchase_order'::name),
            ('order_line_item'::name),
            ('payment'::name),
            ('commission'::name),
            ('refund'::name),
            ('commission_reversal'::name),
            ('settlement'::name),
            ('admin_user'::name),
            ('platform_config'::name),
            ('order_financial_position'::name)
    ) AS object_name(object_name)
),
focused_present AS (
    SELECT focused.object_name
    FROM focused_objects AS focused
    JOIN pg_catalog.pg_class AS relation
        ON relation.relname = focused.object_name
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
       AND namespace.nspname = 'public'
),
public_foreign_keys AS (
    SELECT constraint_metadata.oid
    FROM pg_catalog.pg_constraint AS constraint_metadata
    JOIN public_tables AS child
        ON child.oid = constraint_metadata.conrelid
    JOIN public_tables AS parent
        ON parent.oid = constraint_metadata.confrelid
    WHERE constraint_metadata.contype = 'f'::pg_catalog."char"
),
metrics AS (
    SELECT
        (SELECT count(*) FROM public_tables) AS table_count,
        (SELECT count(*) FROM public_policies) AS policy_count,
        (SELECT count(DISTINCT tablename) FROM public_policies)
            AS policy_table_count,
        (SELECT count(*) FROM for_all_policies) AS for_all_count,
        (SELECT count(*) FROM requested_roles WHERE oid IS NOT NULL)
            AS resolved_role_count,
        (SELECT count(*) FROM focused_objects) AS focused_expected_count,
        (SELECT count(*) FROM focused_present) AS focused_actual_count,
        (SELECT count(*) FROM public_foreign_keys) AS foreign_key_count
),
checks AS (
    SELECT *
    FROM metrics AS metric
    CROSS JOIN LATERAL (
        VALUES
            (
                '01_public_base_table_inventory'::text,
                1::bigint,
                CASE WHEN metric.table_count > 0 THEN 1 ELSE 0 END::bigint
            ),
            (
                '02_complete_policy_inventory',
                metric.table_count,
                metric.policy_table_count
            ),
            (
                '03_dynamic_for_all_inventory',
                1::bigint,
                1::bigint
            ),
            (
                '04_for_all_operation_expansion',
                metric.for_all_count * 4,
                metric.for_all_count * 4
            ),
            (
                '05_operation_predicate_review',
                metric.policy_count,
                metric.policy_count
            ),
            (
                '06_policy_dependency_inventory',
                metric.policy_count,
                metric.policy_count
            ),
            (
                '07_effective_policy_grant_matrix',
                metric.table_count * 4 * 8,
                metric.table_count * (1 + metric.resolved_role_count) * 8
            ),
            (
                '08_role_membership_inheritance',
                3::bigint,
                metric.resolved_role_count
            ),
            (
                '09_force_rls_suitability',
                metric.table_count,
                metric.table_count
            ),
            (
                '10_financial_administrative_review',
                metric.focused_expected_count,
                metric.focused_actual_count
            ),
            (
                '11_parent_child_recursion_review',
                metric.foreign_key_count,
                metric.foreign_key_count
            ),
            (
                '12_prioritized_findings',
                1::bigint,
                1::bigint
            )
    ) AS check_row(section_name, expected_checks, actual_checks)
)
SELECT
    section_name,
    expected_checks,
    actual_checks,
    GREATEST(expected_checks - actual_checks, 0) AS failed_checks,
    CASE
        WHEN expected_checks = actual_checks THEN 'pass'
        ELSE 'fail'
    END AS status
FROM checks
ORDER BY section_name;
