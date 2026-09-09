/*
Phase 3.2A: read-only Supabase security audit.

Run each numbered SELECT separately in the Supabase SQL Editor. Every statement
reads PostgreSQL metadata only. No statement reads application rows or changes
schema, grants, policies, functions, triggers, or data.
*/

-- 01. Every table-like relation in public and its RLS state.
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        WHEN 'f' THEN 'foreign_table'
    END AS table_kind,
    pg_get_userbyid(c.relowner) AS owner_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'f')
ORDER BY c.relname;


-- 02. Direct, PUBLIC-derived, and effective table privileges for API roles.
WITH client_roles(role_name) AS (
    VALUES ('anon'), ('authenticated'), ('service_role')
),
privileges(privilege_name) AS (
    VALUES
        ('SELECT'),
        ('INSERT'),
        ('UPDATE'),
        ('DELETE'),
        ('TRUNCATE'),
        ('REFERENCES'),
        ('TRIGGER')
),
public_tables AS (
    SELECT c.oid, c.relname, c.relacl, c.relowner
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'f')
)
SELECT
    'public' AS schema_name,
    t.relname AS table_name,
    requested.role_name,
    requested_role.oid IS NOT NULL AS role_exists,
    privilege.privilege_name,
    EXISTS (
        SELECT 1
        FROM pg_catalog.aclexplode(
            COALESCE(t.relacl, pg_catalog.acldefault('r', t.relowner))
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = privilege.privilege_name
    ) AS granted_to_public,
    CASE
        WHEN requested_role.oid IS NULL THEN NULL
        ELSE EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(t.relacl, pg_catalog.acldefault('r', t.relowner))
            ) AS acl
            WHERE acl.grantee = requested_role.oid
              AND acl.privilege_type = privilege.privilege_name
        )
    END AS granted_directly,
    CASE
        WHEN requested_role.oid IS NULL THEN NULL
        ELSE pg_catalog.has_table_privilege(
            requested_role.oid,
            t.oid,
            privilege.privilege_name
        )
    END AS effective_privilege
FROM public_tables AS t
CROSS JOIN client_roles AS requested
CROSS JOIN privileges AS privilege
LEFT JOIN pg_catalog.pg_roles AS requested_role
    ON requested_role.rolname = requested.role_name
ORDER BY t.relname, requested.role_name, privilege.privilege_name;


-- 03. Every RLS policy, complete predicates, and targeted review findings.
WITH policy_metadata AS (
    SELECT
        p.schemaname,
        p.tablename,
        p.policyname,
        p.permissive,
        p.roles,
        p.cmd,
        p.qual,
        p.with_check,
        lower(concat_ws(' ', p.qual, p.with_check)) AS combined_expression,
        p.roles && ARRAY['public', 'anon', 'authenticated']::name[]
            AS targets_client_role
    FROM pg_catalog.pg_policies AS p
    WHERE p.schemaname = 'public'
)
SELECT
    schemaname AS schema_name,
    tablename AS table_name,
    policyname AS policy_name,
    permissive,
    roles,
    cmd AS command,
    qual AS using_expression,
    with_check AS with_check_expression,
    array_remove(
        ARRAY[
            CASE
                WHEN tablename = 'product'
                 AND cmd IN ('SELECT', 'ALL')
                 AND targets_client_role
                 AND combined_expression !~ '(lifecycle_state|published)'
                THEN 'HIGH:product_read_policy_missing_published_guard'
            END,
            CASE
                WHEN tablename = 'product'
                 AND cmd IN ('SELECT', 'ALL')
                 AND targets_client_role
                 AND combined_expression
                     !~ '(approval_state|current_party_is_approved)'
                THEN 'HIGH:product_read_policy_missing_seller_approval_guard'
            END,
            CASE
                WHEN tablename = 'category'
                 AND cmd IN ('SELECT', 'ALL')
                 AND targets_client_role
                 AND combined_expression !~ '(is_active)'
                THEN 'HIGH:category_read_policy_missing_active_guard'
            END,
            CASE
                WHEN tablename = 'product_enrichment_assignment'
                 AND cmd IN ('SELECT', 'ALL')
                 AND targets_client_role
                 AND combined_expression
                     !~ '(confirmation_state|party_confirmed)'
                THEN 'HIGH:assignment_read_policy_missing_confirmation_guard'
            END,
            CASE
                WHEN tablename IN (
                    'product_color',
                    'product_image',
                    'product_enrichment_assignment'
                )
                 AND cmd IN ('INSERT', 'UPDATE', 'DELETE', 'ALL')
                 AND targets_client_role
                 AND combined_expression
                     !~ '(current_party_is_approved|approval_state)'
                THEN 'CRITICAL:child_write_policy_missing_approval_guard'
            END,
            CASE
                WHEN tablename = 'marketplace_party'
                 AND cmd IN ('INSERT', 'UPDATE', 'ALL')
                 AND targets_client_role
                THEN 'REVIEW:state_columns_require_grant_or_trigger_protection'
            END
        ],
        NULL
    ) AS metadata_review_findings
FROM policy_metadata
ORDER BY table_name, policy_name;


-- 04. INSERT/UPDATE column privileges on marketplace_party.
WITH audit_roles(role_name, display_order) AS (
    VALUES
        ('anon'::text, 1),
        ('authenticated'::text, 2),
        ('service_role'::text, 3)
),
target_columns AS (
    SELECT
        ordinal_position,
        column_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'marketplace_party'
)
SELECT
    r.role_name,
    c.ordinal_position,
    c.column_name,
    has_table_privilege(
        r.role_name,
        'public.marketplace_party',
        'INSERT'
    ) AS table_insert_granted,
    has_column_privilege(
        r.role_name,
        'public.marketplace_party',
        c.column_name,
        'INSERT'
    ) AS effective_column_insert,
    has_table_privilege(
        r.role_name,
        'public.marketplace_party',
        'UPDATE'
    ) AS table_update_granted,
    has_column_privilege(
        r.role_name,
        'public.marketplace_party',
        c.column_name,
        'UPDATE'
    ) AS effective_column_update
FROM audit_roles AS r
CROSS JOIN target_columns AS c
ORDER BY r.display_order, c.ordinal_position;


-- 05. Triggers that could protect marketplace_party state columns.
WITH target_table AS (
    SELECT c.oid
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'marketplace_party'
      AND c.relkind IN ('r', 'p')
)
SELECT
    'public' AS schema_name,
    'marketplace_party' AS table_name,
    trigger.oid IS NOT NULL AS trigger_present,
    trigger.tgname AS trigger_name,
    CASE trigger.tgenabled
        WHEN 'O' THEN 'origin_and_local'
        WHEN 'D' THEN 'disabled'
        WHEN 'R' THEN 'replica_only'
        WHEN 'A' THEN 'always'
    END AS enabled_mode,
    constraint_row.conname AS constraint_name,
    function_namespace.nspname AS function_schema,
    function_row.proname AS function_name,
    pg_get_userbyid(function_row.proowner) AS function_owner,
    CASE
        WHEN function_row.oid IS NULL THEN NULL
        WHEN function_row.prosecdef THEN 'security_definer'
        ELSE 'security_invoker'
    END AS function_security,
    (
        SELECT regexp_replace(setting, '^search_path=', '')
        FROM unnest(function_row.proconfig) AS setting
        WHERE setting LIKE 'search_path=%'
        LIMIT 1
    ) AS configured_search_path,
    pg_catalog.pg_get_triggerdef(trigger.oid, true) AS trigger_definition,
    COALESCE(protection.enabled_candidate_exists, false)
        AS enabled_state_protection_candidate_exists,
    CASE
        WHEN function_row.oid IS NULL THEN NULL
        ELSE lower(
            pg_catalog.pg_get_triggerdef(trigger.oid, true)
            || ' '
            || function_row.prosrc
        ) LIKE '%approval_state%'
    END AS mentions_approval_state,
    CASE
        WHEN function_row.oid IS NULL THEN NULL
        ELSE lower(
            pg_catalog.pg_get_triggerdef(trigger.oid, true)
            || ' '
            || function_row.prosrc
        ) LIKE '%state_reason%'
    END AS mentions_state_reason,
    COALESCE(
        lower(
            COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
            || ' '
            || COALESCE(function_row.prosrc, '')
        ) LIKE '%approval_state%'
        AND lower(
            COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
            || ' '
            || COALESCE(function_row.prosrc, '')
        ) LIKE '%state_reason%',
        false
    ) AS is_state_protection_candidate,
    CASE
        WHEN NOT COALESCE(protection.enabled_candidate_exists, false)
        THEN 'CRITICAL:no_enabled_state_protection_trigger_candidate_found'
        WHEN COALESCE(
            lower(
                COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
                || ' '
                || COALESCE(function_row.prosrc, '')
            ) LIKE '%approval_state%'
            AND lower(
                COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
                || ' '
                || COALESCE(function_row.prosrc, '')
            ) LIKE '%state_reason%',
            false
        )
         AND function_row.prosecdef
         AND NOT EXISTS (
             SELECT 1
             FROM unnest(function_row.proconfig) AS setting
             WHERE setting LIKE 'search_path=%'
         )
        THEN 'CRITICAL:security_definer_trigger_without_fixed_search_path'
        WHEN COALESCE(
            lower(
                COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
                || ' '
                || COALESCE(function_row.prosrc, '')
            ) LIKE '%approval_state%'
            AND lower(
                COALESCE(pg_catalog.pg_get_triggerdef(trigger.oid, true), '')
                || ' '
                || COALESCE(function_row.prosrc, '')
            ) LIKE '%state_reason%',
            false
        )
        THEN 'REVIEW:verify_trigger_rejects_unauthorized_state_changes'
        ELSE NULL
    END AS risk_finding
FROM target_table AS target
LEFT JOIN LATERAL (
    SELECT bool_or(
        state_trigger.tgenabled <> 'D'
        AND lower(
            pg_catalog.pg_get_triggerdef(state_trigger.oid, true)
            || ' '
            || state_function.prosrc
        ) LIKE '%approval_state%'
        AND lower(
            pg_catalog.pg_get_triggerdef(state_trigger.oid, true)
            || ' '
            || state_function.prosrc
        ) LIKE '%state_reason%'
    ) AS enabled_candidate_exists
    FROM pg_catalog.pg_trigger AS state_trigger
    JOIN pg_catalog.pg_proc AS state_function
        ON state_function.oid = state_trigger.tgfoid
    WHERE state_trigger.tgrelid = target.oid
      AND NOT state_trigger.tgisinternal
) AS protection ON true
LEFT JOIN pg_catalog.pg_trigger AS trigger
    ON trigger.tgrelid = target.oid
   AND NOT trigger.tgisinternal
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.oid = trigger.tgfoid
LEFT JOIN pg_catalog.pg_namespace AS function_namespace
    ON function_namespace.oid = function_row.pronamespace
LEFT JOIN pg_catalog.pg_constraint AS constraint_row
    ON constraint_row.oid = trigger.tgconstraint
ORDER BY trigger.tgname NULLS FIRST;


-- 06. Public views/materialized views, client access, and RLS dependencies.
WITH client_role_oids AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (
            SELECT oid
            FROM pg_catalog.pg_roles
            WHERE rolname = 'authenticated'
        ) AS authenticated_oid
),
public_views AS (
    SELECT c.*
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('v', 'm')
)
SELECT
    'public' AS schema_name,
    view_row.relname AS view_name,
    CASE view_row.relkind
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized_view'
    END AS view_kind,
    pg_get_userbyid(view_row.relowner) AS owner_name,
    CASE
        WHEN view_row.relkind = 'm' THEN 'stored_result_no_runtime_rls'
        WHEN COALESCE(
            view_row.reloptions @> ARRAY['security_invoker=true'],
            false
        ) THEN 'security_invoker'
        ELSE 'owner_rights'
    END AS security_behavior,
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
    ) AS select_granted_to_public,
    CASE
        WHEN roles.anon_oid IS NULL THEN NULL
        ELSE pg_catalog.has_table_privilege(
            roles.anon_oid,
            view_row.oid,
            'SELECT'
        )
    END AS anon_can_select,
    CASE
        WHEN roles.authenticated_oid IS NULL THEN NULL
        ELSE pg_catalog.has_table_privilege(
            roles.authenticated_oid,
            view_row.oid,
            'SELECT'
        )
    END AS authenticated_can_select,
    dependencies.relations AS referenced_relations,
    CASE
        WHEN view_row.relkind = 'm'
         AND (
             COALESCE(
                 pg_catalog.has_table_privilege(
                     roles.anon_oid,
                     view_row.oid,
                     'SELECT'
                 ),
                 false
             )
             OR COALESCE(
                 pg_catalog.has_table_privilege(
                     roles.authenticated_oid,
                     view_row.oid,
                     'SELECT'
                 ),
                 false
             )
         )
        THEN 'CRITICAL:client_readable_materialized_view_requires_manual_review'
        WHEN view_row.relkind = 'v'
         AND NOT COALESCE(
             view_row.reloptions @> ARRAY['security_invoker=true'],
             false
         )
         AND (
             COALESCE(
                 pg_catalog.has_table_privilege(
                     roles.anon_oid,
                     view_row.oid,
                     'SELECT'
                 ),
                 false
             )
             OR COALESCE(
                 pg_catalog.has_table_privilege(
                     roles.authenticated_oid,
                     view_row.oid,
                     'SELECT'
                 ),
                 false
             )
         )
        THEN 'HIGH:client_readable_owner_rights_view_may_bypass_table_rls'
        ELSE NULL
    END AS risk_finding
FROM public_views AS view_row
CROSS JOIN client_role_oids AS roles
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'schema', relation.schema_name,
            'relation', relation.relation_name,
            'kind', relation.relation_kind,
            'rls_enabled', relation.rls_enabled,
            'rls_forced', relation.rls_forced
        )
        ORDER BY relation.schema_name, relation.relation_name
    ) AS relations
    FROM (
        SELECT DISTINCT
            referenced_namespace.nspname AS schema_name,
            referenced.relname AS relation_name,
            CASE referenced.relkind
                WHEN 'r' THEN 'table'
                WHEN 'p' THEN 'partitioned_table'
                WHEN 'f' THEN 'foreign_table'
                WHEN 'v' THEN 'view'
                WHEN 'm' THEN 'materialized_view'
            END AS relation_kind,
            referenced.relrowsecurity AS rls_enabled,
            referenced.relforcerowsecurity AS rls_forced
        FROM pg_catalog.pg_rewrite AS rewrite
        JOIN pg_catalog.pg_depend AS dependency
            ON dependency.classid = 'pg_rewrite'::regclass
           AND dependency.objid = rewrite.oid
           AND dependency.refclassid = 'pg_class'::regclass
        JOIN pg_catalog.pg_class AS referenced
            ON referenced.oid = dependency.refobjid
        JOIN pg_catalog.pg_namespace AS referenced_namespace
            ON referenced_namespace.oid = referenced.relnamespace
        WHERE rewrite.ev_class = view_row.oid
          AND referenced.oid <> view_row.oid
          AND referenced.relkind IN ('r', 'p', 'f', 'v', 'm')
    ) AS relation
) AS dependencies ON true
ORDER BY view_row.relname;


-- 07. Altered default privileges affecting future public-schema objects.
SELECT
    owner_role.rolname AS owner_name,
    COALESCE(namespace.nspname, '<all_schemas>') AS schema_scope,
    CASE defaults.defaclobjtype
        WHEN 'r' THEN 'table'
        WHEN 'S' THEN 'sequence'
        WHEN 'f' THEN 'function'
        WHEN 'T' THEN 'type'
        WHEN 'n' THEN 'schema'
        WHEN 'L' THEN 'large_object'
        ELSE defaults.defaclobjtype::text
    END AS object_type,
    CASE
        WHEN acl.grantee = 0 THEN 'PUBLIC'
        ELSE grantee_role.rolname
    END AS grantee_name,
    acl.privilege_type,
    acl.is_grantable,
    CASE
        WHEN defaults.defaclobjtype = 'r'
         AND COALESCE(grantee_role.rolname, 'PUBLIC')
             IN ('PUBLIC', 'anon', 'authenticated')
         AND acl.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
        THEN 'CRITICAL:new_tables_receive_client_write_privilege'
        WHEN defaults.defaclobjtype = 'r'
         AND COALESCE(grantee_role.rolname, 'PUBLIC')
             IN ('PUBLIC', 'anon', 'authenticated')
         AND acl.privilege_type = 'SELECT'
        THEN 'HIGH:new_tables_receive_client_read_privilege'
        WHEN defaults.defaclobjtype = 'f'
         AND COALESCE(grantee_role.rolname, 'PUBLIC')
             IN ('PUBLIC', 'anon', 'authenticated')
         AND acl.privilege_type = 'EXECUTE'
        THEN 'HIGH:new_functions_receive_client_execute_privilege'
        ELSE NULL
    END AS risk_finding
FROM pg_catalog.pg_default_acl AS defaults
JOIN pg_catalog.pg_roles AS owner_role
    ON owner_role.oid = defaults.defaclrole
LEFT JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = defaults.defaclnamespace
CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
LEFT JOIN pg_catalog.pg_roles AS grantee_role
    ON grantee_role.oid = acl.grantee
WHERE namespace.nspname = 'public'
   OR defaults.defaclnamespace = 0
ORDER BY owner_name, schema_scope, object_type, grantee_name, acl.privilege_type;


-- 08. Required helper-function inventory and signatures.
WITH expected_functions(function_name) AS (
    VALUES
        ('is_admin'),
        ('current_marketplace_party_id'),
        ('current_party_is_approved')
)
SELECT
    expected.function_name AS expected_function_name,
    function_row.oid IS NOT NULL AS function_present,
    function_namespace.nspname AS function_schema,
    function_row.proname AS function_name,
    pg_catalog.pg_get_function_identity_arguments(function_row.oid)
        AS identity_arguments,
    pg_catalog.pg_get_function_result(function_row.oid) AS result_type,
    language.lanname AS language_name,
    CASE function_row.prokind
        WHEN 'f' THEN 'function'
        WHEN 'p' THEN 'procedure'
        WHEN 'a' THEN 'aggregate'
        WHEN 'w' THEN 'window_function'
    END AS function_kind
FROM expected_functions AS expected
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.proname = expected.function_name
   AND function_row.pronamespace = 'public'::regnamespace
LEFT JOIN pg_catalog.pg_namespace AS function_namespace
    ON function_namespace.oid = function_row.pronamespace
LEFT JOIN pg_catalog.pg_language AS language
    ON language.oid = function_row.prolang
WHERE function_row.oid IS NULL
   OR function_namespace.nspname = 'public'
ORDER BY expected.function_name, identity_arguments;


-- 09. Helper-function ownership, execution context, search_path, and grants.
WITH expected_functions(function_name) AS (
    VALUES
        ('is_admin'),
        ('current_marketplace_party_id'),
        ('current_party_is_approved')
),
client_role_oids AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (
            SELECT oid
            FROM pg_catalog.pg_roles
            WHERE rolname = 'authenticated'
        ) AS authenticated_oid,
        (
            SELECT oid
            FROM pg_catalog.pg_roles
            WHERE rolname = 'service_role'
        ) AS service_role_oid
)
SELECT
    expected.function_name AS expected_function_name,
    function_row.oid IS NOT NULL AS function_present,
    pg_catalog.pg_get_function_identity_arguments(function_row.oid)
        AS identity_arguments,
    owner_role.rolname AS owner_name,
    CASE
        WHEN function_row.oid IS NULL THEN NULL
        WHEN function_row.prosecdef THEN 'security_definer'
        ELSE 'security_invoker'
    END AS security_behavior,
    CASE function_row.provolatile
        WHEN 'i' THEN 'immutable'
        WHEN 's' THEN 'stable'
        WHEN 'v' THEN 'volatile'
    END AS volatility,
    (
        SELECT regexp_replace(setting, '^search_path=', '')
        FROM unnest(function_row.proconfig) AS setting
        WHERE setting LIKE 'search_path=%'
        LIMIT 1
    ) AS configured_search_path,
    CASE
        WHEN function_row.oid IS NULL THEN NULL
        ELSE EXISTS (
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
    END AS public_can_execute,
    CASE
        WHEN function_row.oid IS NULL OR roles.anon_oid IS NULL THEN NULL
        ELSE pg_catalog.has_function_privilege(
            roles.anon_oid,
            function_row.oid,
            'EXECUTE'
        )
    END AS anon_can_execute,
    CASE
        WHEN function_row.oid IS NULL OR roles.authenticated_oid IS NULL THEN NULL
        ELSE pg_catalog.has_function_privilege(
            roles.authenticated_oid,
            function_row.oid,
            'EXECUTE'
        )
    END AS authenticated_can_execute,
    CASE
        WHEN function_row.oid IS NULL OR roles.service_role_oid IS NULL THEN NULL
        ELSE pg_catalog.has_function_privilege(
            roles.service_role_oid,
            function_row.oid,
            'EXECUTE'
        )
    END AS service_role_can_execute,
    CASE
        WHEN function_row.oid IS NULL
        THEN 'CRITICAL:required_helper_function_missing'
        WHEN function_row.prosecdef
         AND NOT EXISTS (
             SELECT 1
             FROM unnest(function_row.proconfig) AS setting
             WHERE setting LIKE 'search_path=%'
         )
        THEN 'CRITICAL:security_definer_without_fixed_search_path'
        WHEN function_row.prosecdef
         AND EXISTS (
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
        THEN 'HIGH:public_can_execute_security_definer_function'
        ELSE NULL
    END AS risk_finding
FROM expected_functions AS expected
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.proname = expected.function_name
   AND function_row.pronamespace = 'public'::regnamespace
LEFT JOIN pg_catalog.pg_namespace AS function_namespace
    ON function_namespace.oid = function_row.pronamespace
LEFT JOIN pg_catalog.pg_roles AS owner_role
    ON owner_role.oid = function_row.proowner
CROSS JOIN client_role_oids AS roles
WHERE function_row.oid IS NULL
   OR function_namespace.nspname = 'public'
ORDER BY expected.function_name, identity_arguments;


-- 10. Public tables with effective client grants while RLS is disabled.
WITH client_roles AS (
    SELECT oid, rolname
    FROM pg_catalog.pg_roles
    WHERE rolname IN ('anon', 'authenticated')
),
privileges(privilege_name) AS (
    VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')
),
public_tables AS (
    SELECT c.oid, c.relname, c.relrowsecurity, c.relforcerowsecurity
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'f')
),
effective_access AS (
    SELECT
        table_row.oid,
        table_row.relname,
        table_row.relrowsecurity,
        table_row.relforcerowsecurity,
        role_row.rolname,
        COALESCE(
            array_agg(privilege.privilege_name ORDER BY privilege.privilege_name)
                FILTER (
                    WHERE pg_catalog.has_table_privilege(
                        role_row.oid,
                        table_row.oid,
                        privilege.privilege_name
                    )
                ),
            ARRAY[]::text[]
        ) AS effective_privileges
    FROM public_tables AS table_row
    CROSS JOIN client_roles AS role_row
    CROSS JOIN privileges AS privilege
    GROUP BY
        table_row.oid,
        table_row.relname,
        table_row.relrowsecurity,
        table_row.relforcerowsecurity,
        role_row.rolname
)
SELECT
    'public' AS schema_name,
    access.relname AS table_name,
    access.rolname AS role_name,
    access.effective_privileges,
    access.relrowsecurity AS rls_enabled,
    access.relforcerowsecurity AS rls_forced,
    access.relname ~* '(customer|profile|address|cart|order|payment|admin|offer|review|saved|space)'
        AS sensitive_domain_name,
    CASE
        WHEN access.effective_privileges
            && ARRAY['INSERT', 'UPDATE', 'DELETE']::text[]
        THEN 'CRITICAL:client_write_grant_with_rls_disabled'
        WHEN access.relname
            ~* '(customer|profile|address|cart|order|payment|admin|offer|review|saved|space)'
         AND 'SELECT' = ANY(access.effective_privileges)
        THEN 'CRITICAL:sensitive_table_client_readable_with_rls_disabled'
        WHEN 'SELECT' = ANY(access.effective_privileges)
        THEN 'HIGH:client_read_grant_with_rls_disabled'
    END AS risk_finding
FROM effective_access AS access
WHERE NOT access.relrowsecurity
  AND cardinality(access.effective_privileges) > 0
ORDER BY access.relname, access.rolname;


-- 11. RLS-enabled public tables that have no policies at all.
WITH client_role_oids AS (
    SELECT
        (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'anon') AS anon_oid,
        (
            SELECT oid
            FROM pg_catalog.pg_roles
            WHERE rolname = 'authenticated'
        ) AS authenticated_oid
)
SELECT
    'public' AS schema_name,
    table_row.relname AS table_name,
    table_row.relrowsecurity AS rls_enabled,
    table_row.relforcerowsecurity AS rls_forced,
    CASE
        WHEN roles.anon_oid IS NULL THEN NULL
        ELSE (
            pg_catalog.has_table_privilege(
                roles.anon_oid,
                table_row.oid,
                'SELECT'
            )
            OR pg_catalog.has_table_privilege(
                roles.anon_oid,
                table_row.oid,
                'INSERT'
            )
            OR pg_catalog.has_table_privilege(
                roles.anon_oid,
                table_row.oid,
                'UPDATE'
            )
            OR pg_catalog.has_table_privilege(
                roles.anon_oid,
                table_row.oid,
                'DELETE'
            )
        )
    END AS anon_has_any_crud_privilege,
    CASE
        WHEN roles.authenticated_oid IS NULL THEN NULL
        ELSE (
            pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                table_row.oid,
                'SELECT'
            )
            OR pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                table_row.oid,
                'INSERT'
            )
            OR pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                table_row.oid,
                'UPDATE'
            )
            OR pg_catalog.has_table_privilege(
                roles.authenticated_oid,
                table_row.oid,
                'DELETE'
            )
        )
    END AS authenticated_has_any_crud_privilege,
    'MEDIUM:rls_default_deny_may_be_intentional_review_availability'
        AS risk_finding
FROM pg_catalog.pg_class AS table_row
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = table_row.relnamespace
CROSS JOIN client_role_oids AS roles
WHERE namespace.nspname = 'public'
  AND table_row.relkind IN ('r', 'p', 'f')
  AND table_row.relrowsecurity
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_policy AS policy
      WHERE policy.polrelid = table_row.oid
  )
ORDER BY table_row.relname;


-- 12. Policies using FOR ALL instead of operation-specific commands.
SELECT
    p.schemaname AS schema_name,
    p.tablename AS table_name,
    p.policyname AS policy_name,
    p.permissive,
    p.roles,
    p.cmd AS command,
    p.qual AS using_expression,
    p.with_check AS with_check_expression,
    CASE
        WHEN p.roles && ARRAY['public', 'anon', 'authenticated']::name[]
        THEN 'HIGH:client_policy_uses_for_all_review_each_operation'
        ELSE 'MEDIUM:for_all_policy_should_be_split_by_operation'
    END AS risk_finding
FROM pg_catalog.pg_policies AS p
WHERE p.schemaname = 'public'
  AND p.cmd = 'ALL'
ORDER BY p.tablename, p.policyname;
