/*
Phase 3.2C targeted security hardening -- REVIEW ONLY.

The evidence-backed proposal now includes the live-confirmed furnishing_request
inventory and explicit client column allowlists. It remains unapplied and must
receive another human review before any standalone preflight or migration run.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $phase32c_preflight$
DECLARE
    required_role text;
    missing_tables text;
    unexpected_tables text;
    helper_oid oid;
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
    expected_tables constant text[] := ARRAY[
        'address',
        'admin_user',
        'cart',
        'cart_line',
        'category',
        'commission',
        'commission_reversal',
        'custom_offering',
        'customer_profile',
        'design',
        'design_product_reference',
        'design_version',
        'furnishing_request',
        'furnishing_request_design_version',
        'marketplace_party',
        'offer',
        'offer_line_item',
        'order_line_item',
        'party_capability',
        'payment',
        'platform_config',
        'product',
        'product_3d_model',
        'product_color',
        'product_enrichment_assignment',
        'product_enrichment_attribute',
        'product_image',
        'purchase_order',
        'refund',
        'review',
        'saved_space',
        'service_request',
        'service_type',
        'settlement'
    ];
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C requires PostgreSQL 15 or newer';
    END IF;

    FOREACH required_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role',
        'postgres'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = required_role
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = pg_catalog.format(
                    'Phase 3.2C missing required role: %s',
                    required_role
                );
        END IF;
    END LOOP;

    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon';

    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'authenticated';

    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role';

    SELECT oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'postgres';

    WITH expected(table_name) AS (
        SELECT unnest(expected_tables)
    ),
    actual(table_name) AS (
        SELECT relation.relname::text
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
    ),
    missing AS (
        SELECT table_name FROM expected
        EXCEPT
        SELECT table_name FROM actual
    ),
    unexpected AS (
        SELECT table_name FROM actual
        EXCEPT
        SELECT table_name FROM expected
    )
    SELECT
        (SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM missing),
        (SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM unexpected)
    INTO missing_tables, unexpected_tables;

    IF missing_tables IS NOT NULL OR unexpected_tables IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = pg_catalog.format(
                'Phase 3.2C public table drift; missing=[%s]; unexpected=[%s]',
                COALESCE(missing_tables, 'none'),
                COALESCE(unexpected_tables, 'none')
            );
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
          AND (
              NOT relation.relrowsecurity
              OR relation.relforcerowsecurity
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C RLS/FORCE inventory drift';
    END IF;

    -- PUBLIC is an ACL pseudo-role and is always inspected as grantee OID 0.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                namespace.nspacl,
                pg_catalog.acldefault(
                    'n'::pg_catalog."char",
                    namespace.nspowner
                )
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'USAGE'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                namespace.nspacl,
                pg_catalog.acldefault(
                    'n'::pg_catalog."char",
                    namespace.nspowner
                )
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'CREATE'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C PUBLIC schema privilege drift';
    END IF;

    IF pg_catalog.pg_has_role(
        anon_role_oid,
        service_role_oid,
        'MEMBER'
    ) OR pg_catalog.pg_has_role(
        authenticated_role_oid,
        service_role_oid,
        'MEMBER'
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS role_row
        WHERE role_row.oid IN (anon_role_oid, authenticated_role_oid)
          AND (
              role_row.rolsuper
              OR role_row.rolbypassrls
              OR role_row.rolcreatedb
              OR role_row.rolcreaterole
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C client role elevation drift';
    END IF;

    helper_oid :=
        'public.current_customer_profile_id()'::pg_catalog.regprocedure;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_metadata
        WHERE function_metadata.oid = helper_oid
          AND function_metadata.pronargs = 0
          AND function_metadata.prorettype =
              'pg_catalog.uuid'::pg_catalog.regtype
          AND function_metadata.prolang = (
              SELECT language.oid
              FROM pg_catalog.pg_language AS language
              WHERE language.lanname = 'sql'
          )
          AND function_metadata.provolatile = 's'::pg_catalog."char"
          AND function_metadata.prosecdef
          AND function_metadata.proowner = postgres_role_oid
          AND function_metadata.proconfig =
              ARRAY['search_path=public, pg_temp']::text[]
          AND lower(function_metadata.prosrc)
              LIKE '%public.customer_profile%'
          AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C customer-profile helper signature drift';
    END IF;

    IF NOT pg_catalog.has_function_privilege(
        anon_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT pg_catalog.has_function_privilege(
        authenticated_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT pg_catalog.has_function_privilege(
        service_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT EXISTS (
        SELECT 1
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
        WHERE function_metadata.oid = helper_oid
          AND acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C customer-profile helper grant drift';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_depend AS dependency
            ON dependency.classid =
               'pg_catalog.pg_policy'::pg_catalog.regclass
           AND dependency.objid = policy.oid
           AND dependency.refclassid =
               'pg_catalog.pg_proc'::pg_catalog.regclass
           AND dependency.refobjid = helper_oid
        WHERE 0 = ANY(policy.polroles)
           OR anon_role_oid = ANY(policy.polroles)
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C anonymous policy depends on customer-profile helper';
    END IF;

    -- Exact set reconciliation against the 19 supplied Section 03 policy rows.
    IF EXISTS (
        WITH expected(
            table_name,
            policy_name,
            policy_mode,
            policy_roles
        ) AS (
            VALUES
                ('address'::name, 'address_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart'::name, 'cart_all_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart_line'::name, 'cart_line_all_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('category'::name, 'category_write_admin'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'custom_offering_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('design_product_reference'::name, 'design_product_reference_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('furnishing_request'::name, 'furnishing_request_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('furnishing_request_design_version'::name, 'furnishing_request_design_version_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'offer_line_item_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'party_capability_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('platform_config'::name, 'platform_config_rw_admin'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('product'::name, 'product_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('product_3d_model'::name, 'product_3d_model_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('product_color'::name, 'product_color_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('product_enrichment_assignment'::name, 'product_enrichment_assignment_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('product_image'::name, 'product_image_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('review'::name, 'review_write_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('saved_space'::name, 'saved_space_all_own'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('service_type'::name, 'service_type_write_admin'::name, 'PERMISSIVE'::text, ARRAY['authenticated']::name[])
        ),
        actual AS (
            SELECT
                policy.tablename AS table_name,
                policy.policyname AS policy_name,
                policy.permissive AS policy_mode,
                policy.roles AS policy_roles
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.cmd = 'ALL'
        ),
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.cmd = 'ALL'
    ) <> 19 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C Section 03 FOR ALL identity drift';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.review'::pg_catalog.regclass, 'id'::name),
                ('public.review'::pg_catalog.regclass, 'customer_profile_id'::name),
                ('public.review'::pg_catalog.regclass, 'target_kind'::name),
                ('public.review'::pg_catalog.regclass, 'target_product_id'::name),
                ('public.review'::pg_catalog.regclass, 'target_marketplace_party_id'::name),
                ('public.review'::pg_catalog.regclass, 'target_service_request_id'::name),
                ('public.review'::pg_catalog.regclass, 'rating'::name),
                ('public.review'::pg_catalog.regclass, 'comment'::name),
                ('public.review'::pg_catalog.regclass, 'created_at'::name),
                ('public.service_type'::pg_catalog.regclass, 'id'::name),
                ('public.service_type'::pg_catalog.regclass, 'is_active'::name),
                ('public.party_capability'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('public.party_capability'::pg_catalog.regclass, 'service_type_id'::name)
        ) AS expected_column(table_oid, column_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = expected_column.table_oid
              AND attribute.attname = expected_column.column_name
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C required security column drift';
    END IF;

    -- Exact live-confirmed furnishing_request catalog signature.
    IF EXISTS (
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
                    pg_catalog.format_type(
                        attribute.atttypid,
                        attribute.atttypmod
                    ),
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
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid =
              'public.furnishing_request'::pg_catalog.regclass
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) <> 13 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C furnishing_request inventory drift';
    END IF;

    -- Exact live-confirmed effective INSERT/UPDATE privilege baseline.
    IF EXISTS (
        WITH target_columns(column_name) AS (
            VALUES
                ('id'::name),
                ('customer_profile_id'::name),
                ('address_id'::name),
                ('title'::name),
                ('requirements_description'::name),
                ('reference_image_urls'::name),
                ('budget_min'::name),
                ('budget_max'::name),
                ('requested_timing'::name),
                ('offer_deadline'::name),
                ('lifecycle_state'::name),
                ('created_at'::name),
                ('coarse_location'::name)
        ),
        expected(role_oid, can_insert, can_update) AS (
            VALUES
                (anon_role_oid, false, false),
                (authenticated_role_oid, true, true),
                (service_role_oid, true, true)
        )
        SELECT 1
        FROM expected
        CROSS JOIN target_columns
        WHERE pg_catalog.has_column_privilege(
            expected.role_oid,
            'public.furnishing_request'::pg_catalog.regclass,
            target_columns.column_name,
            'INSERT'
        ) IS DISTINCT FROM expected.can_insert
           OR pg_catalog.has_column_privilege(
               expected.role_oid,
               'public.furnishing_request'::pg_catalog.regclass,
               target_columns.column_name,
               'UPDATE'
           ) IS DISTINCT FROM expected.can_update
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C furnishing_request privilege baseline drift';
    END IF;

    IF ARRAY(
        SELECT attribute.attname::text
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = 'public.review'::pg_catalog.regclass
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY attribute.attname
    ) IS DISTINCT FROM ARRAY[
        'comment',
        'created_at',
        'customer_profile_id',
        'id',
        'rating',
        'target_kind',
        'target_marketplace_party_id',
        'target_product_id',
        'target_service_request_id'
    ] THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C review column inventory drift';
    END IF;

    IF ARRAY(
        SELECT enum_value.enumlabel::text
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_type AS type_metadata
            ON type_metadata.oid = attribute.atttypid
        JOIN pg_catalog.pg_enum AS enum_value
            ON enum_value.enumtypid = type_metadata.oid
        WHERE attribute.attrelid = 'public.review'::pg_catalog.regclass
          AND attribute.attname = 'target_kind'
        ORDER BY enum_value.enumsortorder
    ) IS DISTINCT FROM ARRAY[
        'product',
        'service_request',
        'marketplace_party'
    ] THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C review target-kind enum drift';
    END IF;

    IF ARRAY(
        SELECT enum_value.enumlabel::text
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_type AS type_metadata
            ON type_metadata.oid = attribute.atttypid
        JOIN pg_catalog.pg_enum AS enum_value
            ON enum_value.enumtypid = type_metadata.oid
        WHERE attribute.attrelid =
              'public.furnishing_request'::pg_catalog.regclass
          AND attribute.attname = 'lifecycle_state'
        ORDER BY enum_value.enumsortorder
    ) IS DISTINCT FROM ARRAY[
        'draft',
        'open',
        'accepted',
        'withdrawn',
        'closed'
    ] THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C furnishing lifecycle enum drift';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'review'
          AND policy.policyname = 'review_select_public'
          AND policy.cmd = 'SELECT'
          AND policy.permissive = 'PERMISSIVE'
          AND policy.roles = ARRAY['anon', 'authenticated']::name[]
          AND btrim(lower(policy.qual), '() ') = 'true'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'review'
          AND policy.policyname = 'review_select_admin'
          AND policy.cmd = 'SELECT'
          AND policy.roles = ARRAY['authenticated']::name[]
          AND lower(policy.qual) LIKE '%is_admin%'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'service_type'
          AND policy.policyname = 'service_type_select_public'
          AND policy.cmd = 'SELECT'
          AND policy.roles = ARRAY['anon', 'authenticated']::name[]
          AND btrim(lower(policy.qual), '() ') = 'true'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'party_capability'
          AND policy.policyname = 'party_capability_select'
          AND policy.cmd = 'SELECT'
          AND policy.roles = ARRAY['anon', 'authenticated']::name[]
          AND btrim(lower(policy.qual), '() ') = 'true'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C target policy baseline drift';
    END IF;

    IF NOT pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C review grant baseline drift';
    END IF;

    IF pg_catalog.to_regclass('public.public_review') IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_policies AS policy
           WHERE policy.schemaname = 'public'
             AND policy.policyname LIKE 'phase32c_%'
       )
       OR pg_catalog.to_regprocedure(
           'public.open_furnishing_request(pg_catalog.uuid)'
       ) IS NOT NULL
       OR pg_catalog.to_regprocedure(
           'public.withdraw_furnishing_request(pg_catalog.uuid)'
       ) IS NOT NULL
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C artifacts already exist';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'order_financial_position'
          AND relation.relkind = 'v'::pg_catalog."char"
          AND relation.reloptions @> ARRAY['security_invoker=true']::text[]
    ) OR EXISTS (
        SELECT 1
        FROM information_schema.views AS view_metadata
        WHERE view_metadata.table_schema = 'public'
          AND view_metadata.table_name = 'order_financial_position'
          AND view_metadata.is_updatable <> 'NO'
    ) OR pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C financial view baseline drift';
    END IF;

END
$phase32c_preflight$;

-- Harden the customer identity helper while preserving its UUID contract.
CREATE OR REPLACE FUNCTION public.current_customer_profile_id()
RETURNS pg_catalog.uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT customer.id
    FROM public.customer_profile AS customer
    WHERE customer.user_id = auth.uid()
$function$;

ALTER FUNCTION public.current_customer_profile_id() OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.current_customer_profile_id()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.current_customer_profile_id()
TO authenticated, service_role;

/*
 * Anonymous review reads use only column privileges plus an anon-only RLS
 * policy. No owner-rights view or SECURITY DEFINER review reader is created.
 */
DROP POLICY review_select_public ON public.review;

REVOKE SELECT ON TABLE public.review FROM PUBLIC, anon;
GRANT SELECT (
    id,
    target_kind,
    target_product_id,
    target_marketplace_party_id,
    rating,
    comment,
    created_at
) ON TABLE public.review TO anon;

CREATE POLICY phase32c_review_anon_safe_read
ON public.review
FOR SELECT
TO anon
USING (
    (
        target_kind::text = 'product'
        AND target_product_id IS NOT NULL
        AND target_marketplace_party_id IS NULL
        AND target_service_request_id IS NULL
        AND EXISTS (
            SELECT 1
            FROM public.product AS reviewed_product
            JOIN public.marketplace_party AS product_party
                ON product_party.id =
                   reviewed_product.marketplace_party_id
            JOIN public.category AS product_category
                ON product_category.id = reviewed_product.category_id
            WHERE reviewed_product.id = review.target_product_id
              AND reviewed_product.lifecycle_state =
                  'published'::public.product_state
              AND product_party.approval_state =
                  'approved'::public.party_approval_state
              AND product_category.is_active
              AND EXISTS (
                  SELECT 1
                  FROM public.product_color AS available_color
                  WHERE available_color.product_id =
                        reviewed_product.id
                    AND available_color.stock_quantity > 0
              )
        )
    )
    OR
    (
        target_kind::text = 'marketplace_party'
        AND target_product_id IS NULL
        AND target_marketplace_party_id IS NOT NULL
        AND target_service_request_id IS NULL
        AND EXISTS (
            SELECT 1
            FROM public.marketplace_party AS reviewed_party
            WHERE reviewed_party.id =
                  review.target_marketplace_party_id
              AND reviewed_party.approval_state =
                  'approved'::public.party_approval_state
        )
    )
);

CREATE POLICY phase32c_review_authenticated_read_guard
ON public.review
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    OR public.is_admin()
);

-- Replace literal-true service-directory reads with explicit role paths.
DROP POLICY service_type_select_public ON public.service_type;

CREATE POLICY phase32c_service_type_anon_read
ON public.service_type
FOR SELECT
TO anon
USING (is_active);

CREATE POLICY phase32c_service_type_authenticated_read
ON public.service_type
FOR SELECT
TO authenticated
USING (is_active);

DROP POLICY party_capability_select ON public.party_capability;

CREATE POLICY phase32c_party_capability_anon_read
ON public.party_capability
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.marketplace_party AS capability_party
        WHERE capability_party.id =
              party_capability.marketplace_party_id
          AND capability_party.approval_state =
              'approved'::public.party_approval_state
    )
    AND EXISTS (
        SELECT 1
        FROM public.service_type AS capability_service
        WHERE capability_service.id =
              party_capability.service_type_id
          AND capability_service.is_active
    )
);

CREATE POLICY phase32c_party_capability_authenticated_read
ON public.party_capability
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.marketplace_party AS capability_party
        WHERE capability_party.id =
              party_capability.marketplace_party_id
          AND capability_party.approval_state =
              'approved'::public.party_approval_state
    )
    AND EXISTS (
        SELECT 1
        FROM public.service_type AS capability_service
        WHERE capability_service.id =
              party_capability.service_type_id
          AND capability_service.is_active
    )
);

CREATE POLICY phase32c_party_capability_owner_read
ON public.party_capability
FOR SELECT
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
);

CREATE POLICY phase32c_party_capability_admin_read
ON public.party_capability
FOR SELECT
TO authenticated
USING (public.is_admin());

-- Split customer furnishing writes by operation and lifecycle state.
DROP POLICY furnishing_request_write_own
ON public.furnishing_request;

CREATE POLICY phase32c_furnishing_request_insert_own
ON public.furnishing_request
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state = 'draft'::public.furnishing_request_state
    AND EXISTS (
        SELECT 1
        FROM public.address AS request_address
        WHERE request_address.id = furnishing_request.address_id
          AND request_address.customer_profile_id =
              public.current_customer_profile_id()
    )
);

CREATE POLICY phase32c_furnishing_request_update_own
ON public.furnishing_request
FOR UPDATE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state IN (
        'draft'::public.furnishing_request_state,
        'open'::public.furnishing_request_state
    )
)
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state IN (
        'draft'::public.furnishing_request_state,
        'open'::public.furnishing_request_state
    )
    AND EXISTS (
        SELECT 1
        FROM public.address AS request_address
        WHERE request_address.id = furnishing_request.address_id
          AND request_address.customer_profile_id =
              public.current_customer_profile_id()
    )
);

CREATE POLICY phase32c_furnishing_request_delete_own
ON public.furnishing_request
FOR DELETE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state IN (
        'draft'::public.furnishing_request_state,
        'open'::public.furnishing_request_state
    )
);

/*
 * Normalize authenticated DML completely. Revoking both table privileges and
 * every possible per-column privilege prevents historical column ACLs from
 * surviving before the reviewed allowlists are granted back.
 */
REVOKE INSERT, UPDATE ON TABLE public.furnishing_request
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    address_id,
    title,
    requirements_description,
    reference_image_urls,
    budget_min,
    budget_max,
    requested_timing,
    offer_deadline,
    lifecycle_state,
    created_at,
    coarse_location
), UPDATE (
    id,
    customer_profile_id,
    address_id,
    title,
    requirements_description,
    reference_image_urls,
    budget_min,
    budget_max,
    requested_timing,
    offer_deadline,
    lifecycle_state,
    created_at,
    coarse_location
) ON TABLE public.furnishing_request
FROM authenticated;

GRANT INSERT (
    customer_profile_id,
    address_id,
    title,
    requirements_description,
    reference_image_urls,
    budget_min,
    budget_max,
    requested_timing,
    offer_deadline,
    coarse_location
) ON TABLE public.furnishing_request
TO authenticated;

GRANT UPDATE (
    address_id,
    title,
    requirements_description,
    reference_image_urls,
    budget_min,
    budget_max,
    requested_timing,
    offer_deadline,
    coarse_location
) ON TABLE public.furnishing_request
TO authenticated;

/*
 * These SECURITY DEFINER functions are necessary because lifecycle_state is
 * never directly writable by authenticated callers. Both return only whether
 * the exact owned transition happened, so absence, foreign ownership, and
 * wrong state are indistinguishable.
 */
CREATE OR REPLACE FUNCTION public.open_furnishing_request(
    request_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".furnishing_request AS request_row
    SET lifecycle_state = 'open'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'draft'
      AND EXISTS (
          SELECT 1
          FROM public.customer_profile AS customer
          WHERE customer.id = request_row.customer_profile_id
            AND customer.user_id = auth.uid()
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.open_furnishing_request(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.open_furnishing_request(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.open_furnishing_request(pg_catalog.uuid)
TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.withdraw_furnishing_request(
    request_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".furnishing_request AS request_row
    SET lifecycle_state = 'withdrawn'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'open'
      AND EXISTS (
          SELECT 1
          FROM public.customer_profile AS customer
          WHERE customer.id = request_row.customer_profile_id
            AND customer.user_id = auth.uid()
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.withdraw_furnishing_request(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.withdraw_furnishing_request(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.withdraw_furnishing_request(pg_catalog.uuid)
TO authenticated, service_role;

-- Preserve the invoker-rights financial view and service_role access.
REVOKE ALL PRIVILEGES
ON TABLE public.order_financial_position
FROM PUBLIC, anon, authenticated;
GRANT SELECT
ON TABLE public.order_financial_position
TO authenticated;

DO $phase32c_postflight$
DECLARE
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
    helper_oid oid;
    transition_oid oid;
    transition_name text;
    transition_old_state text;
    transition_new_state text;
    transition_forbidden_states text[];
BEGIN
    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'anon';

    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'authenticated';

    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'service_role';

    SELECT oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'postgres';

    helper_oid :=
        'public.current_customer_profile_id()'::pg_catalog.regprocedure;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_metadata
        WHERE function_metadata.oid = helper_oid
          AND function_metadata.proowner = postgres_role_oid
          AND function_metadata.provolatile = 's'::pg_catalog."char"
          AND function_metadata.prosecdef
          AND function_metadata.proconfig IN
              (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
          AND lower(function_metadata.prosrc)
              LIKE '%public.customer_profile%'
          AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
    ) OR pg_catalog.has_function_privilege(
        anon_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT pg_catalog.has_function_privilege(
        authenticated_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT pg_catalog.has_function_privilege(
        service_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR EXISTS (
        SELECT 1
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
        WHERE function_metadata.oid = helper_oid
          AND acl.privilege_type = 'EXECUTE'
          AND (
              acl.grantee NOT IN (
                  postgres_role_oid,
                  authenticated_role_oid,
                  service_role_oid
              )
              OR (
                  acl.grantee IN (
                      authenticated_role_oid,
                      service_role_oid
                  )
                  AND acl.is_grantable
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight helper mismatch';
    END IF;

    IF pg_catalog.to_regclass('public.public_review') IS NOT NULL
       OR pg_catalog.has_table_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'id',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'target_kind',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'target_product_id',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'target_marketplace_party_id',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'rating',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'comment',
           'SELECT'
       )
       OR NOT pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'created_at',
           'SELECT'
       )
       OR pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'customer_profile_id',
           'SELECT'
       )
       OR pg_catalog.has_column_privilege(
           anon_role_oid,
           'public.review'::pg_catalog.regclass,
           'target_service_request_id',
           'SELECT'
       )
       OR NOT pg_catalog.has_table_privilege(
           authenticated_role_oid,
           'public.review'::pg_catalog.regclass,
           'SELECT'
       )
       OR NOT pg_catalog.has_table_privilege(
           service_role_oid,
           'public.review'::pg_catalog.regclass,
           'SELECT'
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight review column-grant mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('review'::name, 'phase32c_review_anon_safe_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('review'::name, 'phase32c_review_authenticated_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
                ('service_type'::name, 'phase32c_service_type_anon_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('service_type'::name, 'phase32c_service_type_authenticated_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_anon_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_authenticated_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_owner_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_admin_read'::name, 'SELECT'::text, 'PERMISSIVE'::text),
                ('furnishing_request'::name, 'phase32c_furnishing_request_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text),
                ('furnishing_request'::name, 'phase32c_furnishing_request_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text),
                ('furnishing_request'::name, 'phase32c_furnishing_request_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text)
        ) AS expected(table_name, policy_name, command_name, mode_name)
        LEFT JOIN pg_catalog.pg_policies AS actual
            ON actual.schemaname = 'public'
           AND actual.tablename = expected.table_name
           AND actual.policyname = expected.policy_name
        WHERE actual.policyname IS NULL
           OR actual.cmd <> expected.command_name
           OR actual.permissive <> expected.mode_name
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname IN (
              'review_select_public',
              'service_type_select_public',
              'party_capability_select',
              'furnishing_request_write_own'
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight policy inventory mismatch';
    END IF;

    IF EXISTS (
        WITH target_policies AS (
            SELECT
                policyname,
                cmd,
                lower(qual) AS qual,
                lower(with_check) AS with_check
            FROM pg_catalog.pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'furnishing_request'
              AND policyname IN (
                  'phase32c_furnishing_request_insert_own',
                  'phase32c_furnishing_request_update_own',
                  'phase32c_furnishing_request_delete_own'
              )
        )
        SELECT 1
        FROM target_policies
        WHERE NOT (
            CASE cmd
                WHEN 'INSERT' THEN
                    qual IS NULL
                    AND with_check LIKE
                        '%customer_profile_id%current_customer_profile_id%'
                    AND with_check LIKE
                        '%lifecycle_state%draft%furnishing_request_state%'
                    AND with_check LIKE '%public.address%'
                    AND with_check LIKE
                        '%request_address.id%address_id%'
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
                    AND with_check LIKE '%public.address%'
                    AND with_check LIKE
                        '%request_address.id%address_id%'
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
            AND lower(concat_ws(' ', qual, with_check))
                NOT LIKE '%or true%'
        )
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'furnishing_request'
          AND policyname LIKE 'phase32c_furnishing_request_%_own'
    ) <> 3 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight furnishing predicate mismatch';
    END IF;

    FOREACH transition_name IN ARRAY ARRAY[
        'open_furnishing_request',
        'withdraw_furnishing_request'
    ]
    LOOP
        IF transition_name = 'open_furnishing_request' THEN
            transition_old_state := 'draft';
            transition_new_state := 'open';
            transition_forbidden_states := ARRAY[
                'withdrawn',
                'accepted',
                'closed'
            ];
        ELSE
            transition_old_state := 'open';
            transition_new_state := 'withdrawn';
            transition_forbidden_states := ARRAY[
                'draft',
                'accepted',
                'closed'
            ];
        END IF;

        transition_oid := pg_catalog.to_regprocedure(
            pg_catalog.format(
                'public.%I(pg_catalog.uuid)',
                transition_name
            )
        );

        IF transition_oid IS NULL OR NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS function_metadata
            WHERE function_metadata.oid = transition_oid
              AND function_metadata.prorettype =
                  'pg_catalog.bool'::pg_catalog.regtype
              AND function_metadata.prolang = (
                  SELECT language.oid
                  FROM pg_catalog.pg_language AS language
                  WHERE language.lanname = 'plpgsql'
              )
              AND function_metadata.provolatile = 'v'::pg_catalog."char"
              AND function_metadata.prosecdef
              AND function_metadata.proowner = postgres_role_oid
              AND function_metadata.proconfig IN
                  (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
              AND lower(function_metadata.prosrc)
                  LIKE '%"public".furnishing_request%'
              AND lower(function_metadata.prosrc)
                  LIKE '%public.customer_profile%'
              AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
              AND lower(function_metadata.prosrc) LIKE
                  '%lifecycle_state::text = '''
                  || transition_old_state || '''%'
              AND lower(function_metadata.prosrc) LIKE
                  '%set lifecycle_state = '''
                  || transition_new_state || '''%'
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
              AND lower(function_metadata.prosrc)
                  LIKE '%get diagnostics affected_rows = row_count%'
              AND lower(function_metadata.prosrc)
                  LIKE '%affected_rows = 1%'
              AND NOT EXISTS (
                  SELECT 1
                  FROM unnest(transition_forbidden_states)
                      AS forbidden(state_name)
                  WHERE lower(function_metadata.prosrc)
                      LIKE '%''' || forbidden.state_name || '''%'
              )
        ) OR pg_catalog.has_function_privilege(
            anon_role_oid,
            transition_oid,
            'EXECUTE'
        ) OR NOT pg_catalog.has_function_privilege(
            authenticated_role_oid,
            transition_oid,
            'EXECUTE'
        ) OR NOT pg_catalog.has_function_privilege(
            service_role_oid,
            transition_oid,
            'EXECUTE'
        ) OR EXISTS (
            SELECT 1
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
            WHERE function_metadata.oid = transition_oid
              AND acl.privilege_type = 'EXECUTE'
              AND (
                  acl.grantee NOT IN (
                      postgres_role_oid,
                      authenticated_role_oid,
                      service_role_oid
                  )
                  OR (
                      acl.grantee IN (
                          authenticated_role_oid,
                          service_role_oid
                      )
                      AND acl.is_grantable
                  )
              )
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = 'Phase 3.2C postflight transition function mismatch';
        END IF;
    END LOOP;

    IF pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.furnishing_request'::pg_catalog.regclass,
        'INSERT'
    ) OR pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.furnishing_request'::pg_catalog.regclass,
        'UPDATE'
    ) OR EXISTS (
        WITH target_columns(
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
        roles(role_oid, role_name) AS (
            VALUES
                (anon_role_oid, 'anon'::text),
                (authenticated_role_oid, 'authenticated'::text),
                (service_role_oid, 'service_role'::text)
        )
        SELECT 1
        FROM target_columns
        CROSS JOIN roles
        WHERE pg_catalog.has_column_privilege(
            roles.role_oid,
            'public.furnishing_request'::pg_catalog.regclass,
            target_columns.column_name,
            'INSERT'
        ) IS DISTINCT FROM CASE roles.role_name
            WHEN 'anon' THEN false
            WHEN 'authenticated' THEN
                target_columns.authenticated_insert
            ELSE true
        END
           OR pg_catalog.has_column_privilege(
               roles.role_oid,
               'public.furnishing_request'::pg_catalog.regclass,
               target_columns.column_name,
               'UPDATE'
           ) IS DISTINCT FROM CASE roles.role_name
               WHEN 'anon' THEN false
               WHEN 'authenticated' THEN
                   target_columns.authenticated_update
               ELSE true
           END
    ) OR EXISTS (
        WITH target_columns(
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
        expected AS (
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
        actual AS (
            SELECT
                attribute.attname AS column_name,
                acl.privilege_type,
                acl.is_grantable
            FROM pg_catalog.pg_attribute AS attribute
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    attribute.attacl,
                    ARRAY[]::pg_catalog.aclitem[]
                )
            ) AS acl
            WHERE attribute.attrelid =
                  'public.furnishing_request'::pg_catalog.regclass
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND acl.grantee = authenticated_role_oid
              AND acl.privilege_type IN ('INSERT', 'UPDATE')
        ),
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight furnishing column ACL mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'order_financial_position'
          AND relation.relkind = 'v'::pg_catalog."char"
          AND relation.reloptions @> ARRAY['security_invoker=true']::text[]
    ) OR pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.order_financial_position'::pg_catalog.regclass,
        'SELECT'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight financial view mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
          AND (
              NOT relation.relrowsecurity
              OR relation.relforcerowsecurity
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight RLS/FORCE mismatch';
    END IF;
END
$phase32c_postflight$;

COMMIT;
