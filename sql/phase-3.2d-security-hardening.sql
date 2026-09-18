/*
Phase 3.2D targeted security hardening -- REVIEW ONLY.

Splits the ten remaining customer and seller FOR ALL policies by operation,
replaces ownership-only service-request and purchase-order writes with
column allowlists and SECURITY DEFINER transitions, and narrows public
marketplace-party columns. Every embedded catalog signature and privilege
expectation is derived from the read-only evidence under
docs/evidence/phase-3.2d and reconciled by local tests. This file must run
only after the Phase 3.2C migration and must receive human review before any
standalone preflight or migration run.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $phase32d_preflight$
DECLARE
    required_role text;
    missing_tables text;
    unexpected_tables text;
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
    new_function text;
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
    new_functions constant text[] := ARRAY[
        'public.cancel_service_request(pg_catalog.uuid)',
        'public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)',
        'public.start_service_request(pg_catalog.uuid)',
        'public.complete_service_request(pg_catalog.uuid)',
        'public.advance_purchase_order(pg_catalog.uuid, public.order_state)',
        'public.cancel_purchase_order(pg_catalog.uuid)'
    ];
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D requires PostgreSQL 15 or newer';
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
                    'Phase 3.2D missing required role: %s',
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
                'Phase 3.2D table inventory drift; missing: %s; unexpected: %s',
                COALESCE(missing_tables, '(none)'),
                COALESCE(unexpected_tables, '(none)')
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
            MESSAGE = 'Phase 3.2D requires enabled, unforced RLS on every table';
    END IF;

    -- Phase 3.2C must already be applied.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('furnishing_request'::name, 'phase32c_furnishing_request_insert_own'::name),
                ('furnishing_request'::name, 'phase32c_furnishing_request_update_own'::name),
                ('furnishing_request'::name, 'phase32c_furnishing_request_delete_own'::name),
                ('review'::name, 'phase32c_review_anon_safe_read'::name),
                ('review'::name, 'phase32c_review_authenticated_read_guard'::name),
                ('party_capability'::name, 'phase32c_party_capability_owner_read'::name),
                ('party_capability'::name, 'phase32c_party_capability_anon_read'::name),
                ('service_type'::name, 'phase32c_service_type_anon_read'::name)
        ) AS required(table_name, policy_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.tablename = required.table_name
              AND policy.policyname = required.policy_name
        )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname IN (
              'furnishing_request_write_own',
              'review_select_public',
              'party_capability_select',
              'service_type_select_public'
          )
    ) OR pg_catalog.to_regprocedure(
        'public.open_furnishing_request(pg_catalog.uuid)'
    ) IS NULL OR pg_catalog.to_regprocedure(
        'public.withdraw_furnishing_request(pg_catalog.uuid)'
    ) IS NULL OR pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D requires the applied Phase 3.2C migration';
    END IF;

    -- Nothing from this package may already exist.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname LIKE 'phase32d\_%'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D policies already exist';
    END IF;

    FOREACH new_function IN ARRAY new_functions
    LOOP
        IF pg_catalog.to_regprocedure(new_function) IS NOT NULL THEN
            RAISE EXCEPTION USING
                MESSAGE = pg_catalog.format(
                    'Phase 3.2D function already exists: %s',
                    new_function
                );
        END IF;
    END LOOP;

    -- Hardened helpers from Phase 3.2B/3.2C with the expected signatures.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.current_customer_profile_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
                ('public.current_marketplace_party_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
                ('public.current_party_is_approved()'::text, 'pg_catalog.bool'::pg_catalog.regtype),
                ('public.is_admin()'::text, 'pg_catalog.bool'::pg_catalog.regtype)
        ) AS helper(signature, return_type)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS function_metadata
            WHERE function_metadata.oid =
                  pg_catalog.to_regprocedure(helper.signature)
              AND function_metadata.prorettype = helper.return_type
              AND function_metadata.prosecdef
              AND function_metadata.proowner = postgres_role_oid
              AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D helper function drift';
    END IF;

    -- Exact FOR ALL identity set after Phase 3.2C (18 policies).
    IF EXISTS (
        WITH expected(table_name, policy_name) AS (
            VALUES
                ('address'::name, 'address_write_own'::name),
                ('cart'::name, 'cart_all_own'::name),
                ('cart_line'::name, 'cart_line_all_own'::name),
                ('category'::name, 'category_write_admin'::name),
                ('custom_offering'::name, 'custom_offering_write_own'::name),
                ('design_product_reference'::name, 'design_product_reference_write_own'::name),
                ('furnishing_request_design_version'::name, 'furnishing_request_design_version_write_own'::name),
                ('offer_line_item'::name, 'offer_line_item_write_own'::name),
                ('party_capability'::name, 'party_capability_write_own'::name),
                ('platform_config'::name, 'platform_config_rw_admin'::name),
                ('product'::name, 'product_write_own'::name),
                ('product_3d_model'::name, 'product_3d_model_write_own'::name),
                ('product_color'::name, 'product_color_write_own'::name),
                ('product_enrichment_assignment'::name, 'product_enrichment_assignment_write_own'::name),
                ('product_image'::name, 'product_image_write_own'::name),
                ('review'::name, 'review_write_own'::name),
                ('saved_space'::name, 'saved_space_all_own'::name),
                ('service_type'::name, 'service_type_write_admin'::name)
        ),
        actual AS (
            SELECT policy.tablename AS table_name, policy.policyname AS policy_name
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
    ) <> 18 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D FOR ALL identity drift';
    END IF;

    -- Every policy this package replaces must exist with its exact deployed
    -- command, roles, USING, and WITH CHECK text.
    IF EXISTS (
        WITH expected(
            table_name,
            policy_name,
            command_name,
            role_list,
            using_expression,
            check_expression
        ) AS (
            VALUES
                ('address'::name, 'address_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(customer_profile_id = current_customer_profile_id())'::text, '(customer_profile_id = current_customer_profile_id())'::text),
                ('cart'::name, 'cart_all_own'::name, 'ALL'::text, '{authenticated}'::text, '(customer_profile_id = current_customer_profile_id())'::text, '(customer_profile_id = current_customer_profile_id())'::text),
                ('cart_line'::name, 'cart_line_all_own'::name, 'ALL'::text, '{authenticated}'::text, '(EXISTS ( SELECT 1 FROM cart c WHERE ((c.id = cart_line.cart_id) AND (c.customer_profile_id = current_customer_profile_id()))))'::text, '(EXISTS ( SELECT 1 FROM cart c WHERE ((c.id = cart_line.cart_id) AND (c.customer_profile_id = current_customer_profile_id()))))'::text),
                ('custom_offering'::name, 'custom_offering_write_own'::name, 'ALL'::text, '{authenticated}'::text, '((marketplace_party_id = current_marketplace_party_id()) AND current_party_is_approved())'::text, '((marketplace_party_id = current_marketplace_party_id()) AND current_party_is_approved())'::text),
                ('design_product_reference'::name, 'design_product_reference_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(EXISTS ( SELECT 1 FROM design d WHERE ((d.id = design_product_reference.design_id) AND (d.originating_user_id = auth.uid()))))'::text, '(EXISTS ( SELECT 1 FROM design d WHERE ((d.id = design_product_reference.design_id) AND (d.originating_user_id = auth.uid()))))'::text),
                ('furnishing_request_design_version'::name, 'furnishing_request_design_version_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(EXISTS ( SELECT 1 FROM furnishing_request fr WHERE ((fr.id = furnishing_request_design_version.furnishing_request_id) AND (fr.customer_profile_id = current_customer_profile_id()))))'::text, '(EXISTS ( SELECT 1 FROM furnishing_request fr WHERE ((fr.id = furnishing_request_design_version.furnishing_request_id) AND (fr.customer_profile_id = current_customer_profile_id()))))'::text),
                ('offer_line_item'::name, 'offer_line_item_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(EXISTS ( SELECT 1 FROM offer o WHERE ((o.id = offer_line_item.offer_id) AND (o.marketplace_party_id = current_marketplace_party_id()) AND (o.lifecycle_state = ''submitted''::offer_state))))'::text, '(EXISTS ( SELECT 1 FROM offer o WHERE ((o.id = offer_line_item.offer_id) AND (o.marketplace_party_id = current_marketplace_party_id()) AND (o.lifecycle_state = ''submitted''::offer_state))))'::text),
                ('party_capability'::name, 'party_capability_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(marketplace_party_id = current_marketplace_party_id())'::text, '(marketplace_party_id = current_marketplace_party_id())'::text),
                ('purchase_order'::name, 'purchase_order_update_party'::name, 'UPDATE'::text, '{authenticated}'::text, '(marketplace_party_id = current_marketplace_party_id())'::text, '(marketplace_party_id = current_marketplace_party_id())'::text),
                ('review'::name, 'review_write_own'::name, 'ALL'::text, '{authenticated}'::text, '(customer_profile_id = current_customer_profile_id())'::text, '(customer_profile_id = current_customer_profile_id())'::text),
                ('saved_space'::name, 'saved_space_all_own'::name, 'ALL'::text, '{authenticated}'::text, '(customer_profile_id = current_customer_profile_id())'::text, '(customer_profile_id = current_customer_profile_id())'::text),
                ('service_request'::name, 'service_request_insert_own'::name, 'INSERT'::text, '{authenticated}'::text, NULL::text, '(customer_profile_id = current_customer_profile_id())'::text),
                ('service_request'::name, 'service_request_update_engaged'::name, 'UPDATE'::text, '{authenticated}'::text, '((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id()))'::text, '((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id()))'::text)
        )
        SELECT 1
        FROM expected
        LEFT JOIN pg_catalog.pg_policies AS actual
            ON actual.schemaname = 'public'
           AND actual.tablename = expected.table_name
           AND actual.policyname = expected.policy_name
        WHERE actual.policyname IS NULL
           OR actual.cmd <> expected.command_name
           OR actual.permissive <> 'PERMISSIVE'
           OR actual.roles::text <> expected.role_list
           -- The expected text was recorded in the SQL Editor, where public is
           -- on the search path; here it is not, so the same policy prints
           -- public.current_customer_profile_id() and FROM public.cart. Only
           -- that qualifier is removed; any other schema still differs.
           OR pg_catalog.regexp_replace(
                  pg_catalog.replace(actual.qual, 'public.', ''), '\s+', ' ', 'g'
              ) IS DISTINCT FROM expected.using_expression
           OR pg_catalog.regexp_replace(
                  pg_catalog.replace(actual.with_check, 'public.', ''),
                  '\s+',
                  ' ',
                  'g'
              ) IS DISTINCT FROM expected.check_expression
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D replaced policy drift';
    END IF;

    -- Exact live-confirmed column signatures of the thirteen touched tables.
    IF EXISTS (
        WITH expected(
            table_name,
            ordinal_position,
            column_name,
            formatted_type,
            column_type,
            type_modifier,
            is_not_null,
            default_expression,
            generated_kind
        ) AS (
            VALUES
                ('address'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('address'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 3, 'label'::name, 'address_label'::text, 'public.address_label'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 4, 'recipient_name'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 5, 'contact_phone'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 6, 'address_line_1'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 7, 'address_line_2'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 8, 'city'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 9, 'country'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 10, 'latitude'::name, 'numeric(9,6)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 589834, false, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 11, 'longitude'::name, 'numeric(9,6)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 589834, false, NULL::text, ''::pg_catalog."char"),
                ('address'::name, 12, 'is_default'::name, 'boolean'::text, 'pg_catalog.bool'::pg_catalog.regtype, -1, true, 'false'::text, ''::pg_catalog."char"),
                ('cart'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('cart'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('cart_line'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('cart_line'::name, 2, 'cart_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('cart_line'::name, 3, 'product_color_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('cart_line'::name, 4, 'quantity'::name, 'integer'::text, 'pg_catalog.int4'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('saved_space'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('saved_space'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('saved_space'::name, 3, 'space_name'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('saved_space'::name, 4, 'width_cm'::name, 'numeric(8,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 524294, true, NULL::text, ''::pg_catalog."char"),
                ('saved_space'::name, 5, 'depth_cm'::name, 'numeric(8,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 524294, true, NULL::text, ''::pg_catalog."char"),
                ('saved_space'::name, 6, 'measurement_source'::name, 'measurement_source'::text, 'public.measurement_source'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('review'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 3, 'target_kind'::name, 'review_target_kind'::text, 'public.review_target_kind'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 4, 'target_product_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 5, 'target_service_request_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 6, 'target_marketplace_party_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 7, 'rating'::name, 'smallint'::text, 'pg_catalog.int2'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 8, 'comment'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('review'::name, 9, 'created_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, true, 'now()'::text, ''::pg_catalog."char"),
                ('furnishing_request_design_version'::name, 1, 'furnishing_request_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('furnishing_request_design_version'::name, 2, 'design_version_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 2, 'marketplace_party_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 3, 'design_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 4, 'published_price'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, true, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 5, 'title'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 6, 'description'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 7, 'publication_state'::name, 'custom_offering_state'::text, 'public.custom_offering_state'::pg_catalog.regtype, -1, true, '''unpublished''::custom_offering_state'::text, ''::pg_catalog."char"),
                ('custom_offering'::name, 8, 'published_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('party_capability'::name, 1, 'marketplace_party_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('party_capability'::name, 2, 'service_type_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('party_capability'::name, 3, 'declared_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 2, 'offer_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 3, 'line_kind'::name, 'line_kind'::text, 'public.line_kind'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 4, 'product_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 5, 'item_name'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 6, 'specification'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 7, 'unit_price'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, true, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 8, 'quantity'::name, 'integer'::text, 'pg_catalog.int4'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('offer_line_item'::name, 9, 'line_total'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, false, '(unit_price * (quantity)::numeric)'::text, 's'::pg_catalog."char"),
                ('offer_line_item'::name, 10, 'display_order'::name, 'integer'::text, 'pg_catalog.int4'::pg_catalog.regtype, -1, true, '0'::text, ''::pg_catalog."char"),
                ('design_product_reference'::name, 1, 'design_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('design_product_reference'::name, 2, 'product_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('service_request'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 3, 'service_type_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 4, 'marketplace_party_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 5, 'address_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 6, 'related_order_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 7, 'scheduled_date'::name, 'date'::text, 'pg_catalog.date'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 8, 'scheduled_time'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 9, 'details'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 10, 'price'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 11, 'lifecycle_state'::name, 'service_request_state'::text, 'public.service_request_state'::pg_catalog.regtype, -1, true, '''pending''::service_request_state'::text, ''::pg_catalog."char"),
                ('service_request'::name, 12, 'accepted_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 13, 'completed_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('service_request'::name, 14, 'created_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, true, 'now()'::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 2, 'customer_profile_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 3, 'marketplace_party_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 4, 'address_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 5, 'origin'::name, 'order_origin'::text, 'public.order_origin'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 6, 'offer_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 7, 'custom_offering_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 8, 'service_request_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 9, 'settlement_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 10, 'lifecycle_state'::name, 'order_state'::text, 'public.order_state'::pg_catalog.regtype, -1, true, '''pending''::order_state'::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 11, 'order_discount_amount'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 12, 'delivery_fee'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, true, '0'::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 13, 'required_upfront_amount'::name, 'numeric(12,2)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 786438, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 14, 'notes'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 15, 'placed_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, true, 'now()'::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 16, 'cancelled_at'::name, 'timestamp with time zone'::text, 'pg_catalog.timestamptz'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 17, 'ship_recipient_name'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 18, 'ship_contact_phone'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 19, 'ship_address_line_1'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 20, 'ship_address_line_2'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 21, 'ship_city'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 22, 'ship_country'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 23, 'ship_latitude'::name, 'numeric(9,6)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 589834, false, NULL::text, ''::pg_catalog."char"),
                ('purchase_order'::name, 24, 'ship_longitude'::name, 'numeric(9,6)'::text, 'pg_catalog.numeric'::pg_catalog.regtype, 589834, false, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 1, 'id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, 'gen_random_uuid()'::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 2, 'user_id'::name, 'uuid'::text, 'pg_catalog.uuid'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 3, 'business_name'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, true, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 4, 'business_description'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 5, 'logo_url'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 6, 'coverage_area'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 7, 'approval_state'::name, 'party_approval_state'::text, 'public.party_approval_state'::pg_catalog.regtype, -1, true, '''pending''::party_approval_state'::text, ''::pg_catalog."char"),
                ('marketplace_party'::name, 8, 'state_reason'::name, 'text'::text, 'pg_catalog.text'::pg_catalog.regtype, -1, false, NULL::text, ''::pg_catalog."char")
        ),
        actual AS (
            SELECT
                relation.relname AS table_name,
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
                attribute.atttypid::pg_catalog.regtype AS column_type,
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
                attribute.attgenerated AS generated_kind
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_attribute AS attribute
                ON attribute.attrelid = relation.oid
            LEFT JOIN pg_catalog.pg_attrdef AS column_default
                ON column_default.adrelid = attribute.attrelid
               AND column_default.adnum = attribute.attnum
            WHERE namespace.nspname = 'public'
              AND relation.relname IN (SELECT DISTINCT table_name FROM expected)
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
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (

              'address',
              'cart',
              'cart_line',
              'saved_space',
              'review',
              'furnishing_request_design_version',
              'custom_offering',
              'party_capability',
              'offer_line_item',
              'design_product_reference',
              'service_request',
              'purchase_order',
              'marketplace_party'
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) <> 104 OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (

              'address',
              'cart',
              'cart_line',
              'saved_space',
              'review',
              'furnishing_request_design_version',
              'custom_offering',
              'party_capability',
              'offer_line_item',
              'design_product_reference',
              'service_request',
              'purchase_order',
              'marketplace_party'
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND attribute.attidentity <> ''
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D column inventory drift';
    END IF;

    -- Exact effective privilege baseline (after Phase 3.2C) for every column
    -- of the touched tables and the three API roles.
    IF EXISTS (
        WITH expected(
            table_name,
            column_name,
            role_name,
            table_select,
            table_insert,
            table_update,
            table_delete,
            column_select,
            column_insert,
            column_update
        ) AS (
            VALUES
                ('address'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'label'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'label'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'label'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'recipient_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'recipient_name'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'recipient_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'contact_phone'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'contact_phone'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'contact_phone'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_1'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'address_line_1'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_1'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_2'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'address_line_2'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_2'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'city'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'city'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'city'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'country'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'country'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'country'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'latitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'latitude'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'latitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'longitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'longitude'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'longitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'is_default'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'is_default'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('address'::name, 'is_default'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'cart_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'cart_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'cart_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'product_color_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'product_color_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'product_color_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'quantity'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'quantity'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'quantity'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'space_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'space_name'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'space_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'width_cm'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'width_cm'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'width_cm'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'depth_cm'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'depth_cm'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'depth_cm'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'measurement_source'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'measurement_source'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'measurement_source'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('review'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_kind'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_kind'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_kind'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_product_id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_product_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_service_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('review'::name, 'target_service_request_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_service_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_marketplace_party_id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_marketplace_party_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'rating'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'rating'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'rating'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'comment'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'comment'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'comment'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'created_at'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'created_at'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('review'::name, 'created_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'design_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'design_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'design_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_price'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'published_price'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'title'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'title'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'title'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'description'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'description'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'description'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'publication_state'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'publication_state'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'publication_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_at'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'published_at'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'marketplace_party_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'service_type_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'service_type_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'service_type_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'declared_at'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'declared_at'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'declared_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'offer_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'offer_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'offer_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_kind'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'line_kind'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_kind'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'product_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'product_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'item_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'item_name'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'item_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'specification'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'specification'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'specification'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'unit_price'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'unit_price'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'unit_price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'quantity'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'quantity'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'quantity'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_total'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'line_total'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_total'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'display_order'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'display_order'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'display_order'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'design_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('design_product_reference'::name, 'design_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'design_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'product_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('design_product_reference'::name, 'product_id'::name, 'authenticated'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'service_type_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'service_type_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'service_type_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'marketplace_party_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'address_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'address_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'address_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'related_order_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'related_order_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'related_order_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'scheduled_date'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'scheduled_date'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('service_request'::name, 'scheduled_date'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'scheduled_time'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'scheduled_time'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('service_request'::name, 'scheduled_time'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'details'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'details'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('service_request'::name, 'details'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'price'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'price'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'lifecycle_state'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'lifecycle_state'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('service_request'::name, 'lifecycle_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'accepted_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'accepted_at'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'accepted_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'completed_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'completed_at'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('service_request'::name, 'completed_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'created_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'created_at'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('service_request'::name, 'created_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'customer_profile_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'address_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'address_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'address_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'origin'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'origin'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'origin'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'offer_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'offer_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'offer_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'custom_offering_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'custom_offering_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'custom_offering_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'service_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'service_request_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'service_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'settlement_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'settlement_id'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'settlement_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'lifecycle_state'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'lifecycle_state'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('purchase_order'::name, 'lifecycle_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'order_discount_amount'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'order_discount_amount'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'order_discount_amount'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'delivery_fee'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'delivery_fee'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'delivery_fee'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'notes'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'notes'::name, 'authenticated'::text, true, true, false, true, true, true, true),
                ('purchase_order'::name, 'notes'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'placed_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'placed_at'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'placed_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'cancelled_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'cancelled_at'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'cancelled_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_city'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_city'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_city'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_country'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_country'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_country'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_latitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_latitude'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_latitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_longitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_longitude'::name, 'authenticated'::text, true, true, false, true, true, true, false),
                ('purchase_order'::name, 'ship_longitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('marketplace_party'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'user_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'user_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('marketplace_party'::name, 'user_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'business_name'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'business_name'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('marketplace_party'::name, 'business_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'business_description'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'business_description'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('marketplace_party'::name, 'business_description'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'logo_url'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'logo_url'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('marketplace_party'::name, 'logo_url'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'coverage_area'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'coverage_area'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('marketplace_party'::name, 'coverage_area'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'approval_state'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'approval_state'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('marketplace_party'::name, 'approval_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'state_reason'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('marketplace_party'::name, 'state_reason'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('marketplace_party'::name, 'state_reason'::name, 'service_role'::text, true, true, true, true, true, true, true)
        ),
        roles(role_name, role_oid) AS (
            VALUES
                ('anon'::text, anon_role_oid),
                ('authenticated'::text, authenticated_role_oid),
                ('service_role'::text, service_role_oid)
        )
        SELECT 1
        FROM expected
        JOIN roles ON roles.role_name = expected.role_name
        CROSS JOIN LATERAL (
            SELECT
                pg_catalog.to_regclass('public.' || expected.table_name)
                    AS table_oid
        ) AS target
        WHERE target.table_oid IS NULL
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'SELECT')
              IS DISTINCT FROM expected.table_select
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'INSERT')
              IS DISTINCT FROM expected.table_insert
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'UPDATE')
              IS DISTINCT FROM expected.table_update
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'DELETE')
              IS DISTINCT FROM expected.table_delete
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'SELECT'
              ) IS DISTINCT FROM expected.column_select
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'INSERT'
              ) IS DISTINCT FROM expected.column_insert
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'UPDATE'
              ) IS DISTINCT FROM expected.column_update
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D privilege baseline drift';
    END IF;

    -- Constraints and enum labels the new predicates and functions rely on.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('cart'::name, 'cart_customer_unique'::name),
                ('cart_line'::name, 'cart_line_unique_per_color'::name),
                ('customer_profile'::name, 'customer_profile_user_unique'::name),
                ('marketplace_party'::name, 'marketplace_party_user_unique'::name),
                ('review'::name, 'review_exactly_one_target'::name),
                ('review'::name, 'review_target_kind_agreement'::name),
                ('service_request'::name, 'service_request_executor_when_claimed'::name),
                ('service_request'::name, 'service_request_priced_when_claimed'::name),
                ('service_request'::name, 'service_request_completed_timestamp'::name),
                ('service_request'::name, 'service_request_address_fk'::name),
                ('purchase_order'::name, 'purchase_order_cancelled_timestamp'::name),
                ('purchase_order'::name, 'purchase_order_custom_offering_fk'::name),
                ('purchase_order'::name, 'purchase_order_address_fk'::name),
                ('furnishing_request'::name, 'furnishing_request_address_fk'::name)
        ) AS required(table_name, constraint_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
                ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = required.table_name
              AND constraint_row.conname = required.constraint_name
        )
    ) OR EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('service_request_state'::name, ARRAY['pending', 'accepted', 'in_progress', 'completed', 'cancelled']::text[]),
                ('order_state'::name, ARRAY['pending', 'confirmed', 'preparing', 'out_for_delivery', 'delivered', 'cancelled']::text[]),
                ('furnishing_request_state'::name, ARRAY['draft', 'open', 'accepted', 'withdrawn', 'closed']::text[]),
                ('review_target_kind'::name, ARRAY['product', 'service_request', 'marketplace_party']::text[]),
                ('party_approval_state'::name, ARRAY['pending', 'approved', 'rejected', 'suspended']::text[]),
                ('offer_state'::name, ARRAY['submitted', 'accepted', 'rejected', 'withdrawn', 'expired']::text[]),
                ('custom_offering_state'::name, ARRAY['published', 'unpublished']::text[])
        ) AS expected_enum(type_name, labels)
        WHERE (
            SELECT array_agg(enum_label.enumlabel::text ORDER BY enum_label.enumsortorder)
            FROM pg_catalog.pg_type AS enum_type
            JOIN pg_catalog.pg_namespace AS type_namespace
                ON type_namespace.oid = enum_type.typnamespace
            JOIN pg_catalog.pg_enum AS enum_label
                ON enum_label.enumtypid = enum_type.oid
            WHERE type_namespace.nspname = 'public'
              AND enum_type.typname = expected_enum.type_name
        ) IS DISTINCT FROM expected_enum.labels
    ) OR EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.product'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('public.product'::pg_catalog.regclass, 'category_id'::name),
                ('public.product'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.product_color'::pg_catalog.regclass, 'product_id'::name),
                ('public.product_color'::pg_catalog.regclass, 'stock_quantity'::name),
                ('public.category'::pg_catalog.regclass, 'is_active'::name),
                ('public.service_type'::pg_catalog.regclass, 'is_active'::name),
                ('public.offer'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('public.offer'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.design'::pg_catalog.regclass, 'originating_user_id'::name),
                ('public.order_line_item'::pg_catalog.regclass, 'order_id'::name),
                ('public.order_line_item'::pg_catalog.regclass, 'product_id'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'address_id'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.customer_profile'::pg_catalog.regclass, 'user_id'::name)
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
            MESSAGE = 'Phase 3.2D required constraint, enum, or column drift';
    END IF;
END
$phase32d_preflight$;

-- A1. address: split the FOR ALL policy; deletes stay blocked while referenced.
DROP POLICY address_write_own ON public.address;

CREATE POLICY phase32d_address_insert_own
ON public.address
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_address_update_own
ON public.address
FOR UPDATE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
)
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_address_delete_own
ON public.address
FOR DELETE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND NOT EXISTS (
        SELECT 1
        FROM public.furnishing_request AS referencing_request
        WHERE referencing_request.address_id = address.id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.service_request AS referencing_service
        WHERE referencing_service.address_id = address.id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.purchase_order AS referencing_order
        WHERE referencing_order.address_id = address.id
    )
);

REVOKE INSERT, UPDATE ON TABLE public.address
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    label,
    recipient_name,
    contact_phone,
    address_line_1,
    address_line_2,
    city,
    country,
    latitude,
    longitude,
    is_default
), UPDATE (
    id,
    customer_profile_id,
    label,
    recipient_name,
    contact_phone,
    address_line_1,
    address_line_2,
    city,
    country,
    latitude,
    longitude,
    is_default
) ON TABLE public.address
FROM authenticated;

GRANT INSERT (
    customer_profile_id,
    label,
    recipient_name,
    contact_phone,
    address_line_1,
    address_line_2,
    city,
    country,
    latitude,
    longitude,
    is_default
) ON TABLE public.address
TO authenticated;

GRANT UPDATE (
    label,
    recipient_name,
    contact_phone,
    address_line_1,
    address_line_2,
    city,
    country,
    latitude,
    longitude,
    is_default
) ON TABLE public.address
TO authenticated;

-- A1. cart: one server-created cart per customer; the client reads and deletes.
DROP POLICY cart_all_own ON public.cart;

CREATE POLICY phase32d_cart_select_own
ON public.cart
FOR SELECT
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_cart_delete_own
ON public.cart
FOR DELETE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
);

REVOKE INSERT, UPDATE ON TABLE public.cart
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id
), UPDATE (
    id,
    customer_profile_id
) ON TABLE public.cart
FROM authenticated;

-- A2. cart_line: owned cart, eligible catalogue colour at insert, quantity edits.
DROP POLICY cart_line_all_own ON public.cart_line;

CREATE POLICY phase32d_cart_line_select_own
ON public.cart_line
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )
);

CREATE POLICY phase32d_cart_line_insert_own
ON public.cart_line
FOR INSERT
TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )
    AND EXISTS (
        SELECT 1
        FROM public.product_color AS chosen_color
        JOIN public.product AS chosen_product
            ON chosen_product.id = chosen_color.product_id
        JOIN public.marketplace_party AS product_party
            ON product_party.id = chosen_product.marketplace_party_id
        JOIN public.category AS product_category
            ON product_category.id = chosen_product.category_id
        WHERE chosen_color.id = cart_line.product_color_id
          AND chosen_product.lifecycle_state =
              'published'::public.product_state
          AND product_party.approval_state =
              'approved'::public.party_approval_state
          AND product_category.is_active
          AND chosen_color.stock_quantity > 0
    )
);

CREATE POLICY phase32d_cart_line_update_own
ON public.cart_line
FOR UPDATE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )
);

CREATE POLICY phase32d_cart_line_delete_own
ON public.cart_line
FOR DELETE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )
);

REVOKE INSERT, UPDATE ON TABLE public.cart_line
FROM authenticated;

REVOKE INSERT (
    id,
    cart_id,
    product_color_id,
    quantity
), UPDATE (
    id,
    cart_id,
    product_color_id,
    quantity
) ON TABLE public.cart_line
FROM authenticated;

GRANT INSERT (
    cart_id,
    product_color_id,
    quantity
) ON TABLE public.cart_line
TO authenticated;

GRANT UPDATE (
    quantity
) ON TABLE public.cart_line
TO authenticated;

-- A1. saved_space: owner-scoped per operation with a column allowlist.
DROP POLICY saved_space_all_own ON public.saved_space;

CREATE POLICY phase32d_saved_space_select_own
ON public.saved_space
FOR SELECT
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_saved_space_insert_own
ON public.saved_space
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_saved_space_update_own
ON public.saved_space
FOR UPDATE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
)
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_saved_space_delete_own
ON public.saved_space
FOR DELETE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
);

REVOKE INSERT, UPDATE ON TABLE public.saved_space
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    space_name,
    width_cm,
    depth_cm,
    measurement_source
), UPDATE (
    id,
    customer_profile_id,
    space_name,
    width_cm,
    depth_cm,
    measurement_source
) ON TABLE public.saved_space
FROM authenticated;

GRANT INSERT (
    customer_profile_id,
    space_name,
    width_cm,
    depth_cm,
    measurement_source
) ON TABLE public.saved_space
TO authenticated;

GRANT UPDATE (
    space_name,
    width_cm,
    depth_cm,
    measurement_source
) ON TABLE public.saved_space
TO authenticated;

-- A1. review: insert-only, final, verified purchase or completed service.
DROP POLICY review_write_own ON public.review;

CREATE POLICY phase32d_review_select_own
ON public.review
FOR SELECT
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
);

CREATE POLICY phase32d_review_insert_verified
ON public.review
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND (
        (
            target_kind = 'product'::public.review_target_kind
            AND target_product_id IS NOT NULL
            AND target_service_request_id IS NULL
            AND target_marketplace_party_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.order_line_item AS purchased_line
                JOIN public.purchase_order AS purchased_order
                    ON purchased_order.id = purchased_line.order_id
                WHERE purchased_line.product_id = review.target_product_id
                  AND purchased_order.customer_profile_id =
                      public.current_customer_profile_id()
                  AND purchased_order.lifecycle_state =
                      'delivered'::public.order_state
            )
        )
        OR (
            target_kind = 'service_request'::public.review_target_kind
            AND target_product_id IS NULL
            AND target_service_request_id IS NOT NULL
            AND target_marketplace_party_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.service_request AS reviewed_request
                WHERE reviewed_request.id = review.target_service_request_id
                  AND reviewed_request.customer_profile_id =
                      public.current_customer_profile_id()
                  AND reviewed_request.lifecycle_state =
                      'completed'::public.service_request_state
            )
        )
        OR (
            target_kind = 'marketplace_party'::public.review_target_kind
            AND target_product_id IS NULL
            AND target_service_request_id IS NULL
            AND target_marketplace_party_id IS NOT NULL
            AND (
                EXISTS (
                    SELECT 1
                    FROM public.purchase_order AS party_order
                    WHERE party_order.marketplace_party_id =
                          review.target_marketplace_party_id
                      AND party_order.customer_profile_id =
                          public.current_customer_profile_id()
                      AND party_order.lifecycle_state =
                          'delivered'::public.order_state
                )
                OR EXISTS (
                    SELECT 1
                    FROM public.service_request AS party_request
                    WHERE party_request.marketplace_party_id =
                          review.target_marketplace_party_id
                      AND party_request.customer_profile_id =
                          public.current_customer_profile_id()
                      AND party_request.lifecycle_state =
                          'completed'::public.service_request_state
                )
            )
        )
    )
);

REVOKE INSERT, UPDATE ON TABLE public.review
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    target_kind,
    target_product_id,
    target_service_request_id,
    target_marketplace_party_id,
    rating,
    comment,
    created_at
), UPDATE (
    id,
    customer_profile_id,
    target_kind,
    target_product_id,
    target_service_request_id,
    target_marketplace_party_id,
    rating,
    comment,
    created_at
) ON TABLE public.review
FROM authenticated;

GRANT INSERT (
    customer_profile_id,
    target_kind,
    target_product_id,
    target_service_request_id,
    target_marketplace_party_id,
    rating,
    comment
) ON TABLE public.review
TO authenticated;

-- A2. furnishing_request_design_version: server-created; owner deletes while
-- the parent request is draft or open.
DROP POLICY furnishing_request_design_version_write_own
ON public.furnishing_request_design_version;

CREATE POLICY phase32d_furnishing_request_design_version_delete_own
ON public.furnishing_request_design_version
FOR DELETE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.furnishing_request AS parent_request
        WHERE parent_request.id =
              furnishing_request_design_version.furnishing_request_id
          AND parent_request.customer_profile_id =
              public.current_customer_profile_id()
          AND parent_request.lifecycle_state IN (
              'draft'::public.furnishing_request_state,
              'open'::public.furnishing_request_state
          )
    )
);

REVOKE INSERT, UPDATE ON TABLE public.furnishing_request_design_version
FROM authenticated;

REVOKE INSERT (
    furnishing_request_id,
    design_version_id
), UPDATE (
    furnishing_request_id,
    design_version_id
) ON TABLE public.furnishing_request_design_version
FROM authenticated;

-- A3. custom_offering: approved owner, own design, no delete once ordered.
DROP POLICY custom_offering_write_own ON public.custom_offering;

CREATE POLICY phase32d_custom_offering_insert_own
ON public.custom_offering
FOR INSERT
TO authenticated
WITH CHECK (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
    AND EXISTS (
        SELECT 1
        FROM public.design AS offered_design
        WHERE offered_design.id = custom_offering.design_id
          AND offered_design.originating_user_id = auth.uid()
    )
);

CREATE POLICY phase32d_custom_offering_update_own
ON public.custom_offering
FOR UPDATE
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
)
WITH CHECK (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
    AND EXISTS (
        SELECT 1
        FROM public.design AS offered_design
        WHERE offered_design.id = custom_offering.design_id
          AND offered_design.originating_user_id = auth.uid()
    )
);

CREATE POLICY phase32d_custom_offering_delete_own
ON public.custom_offering
FOR DELETE
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
    AND NOT EXISTS (
        SELECT 1
        FROM public.purchase_order AS referencing_order
        WHERE referencing_order.custom_offering_id = custom_offering.id
    )
);

REVOKE INSERT, UPDATE ON TABLE public.custom_offering
FROM authenticated;

REVOKE INSERT (
    id,
    marketplace_party_id,
    design_id,
    published_price,
    title,
    description,
    publication_state,
    published_at
), UPDATE (
    id,
    marketplace_party_id,
    design_id,
    published_price,
    title,
    description,
    publication_state,
    published_at
) ON TABLE public.custom_offering
FROM authenticated;

GRANT INSERT (
    marketplace_party_id,
    design_id,
    published_price,
    title,
    description,
    publication_state,
    published_at
) ON TABLE public.custom_offering
TO authenticated;

GRANT UPDATE (
    design_id,
    published_price,
    title,
    description,
    publication_state,
    published_at
) ON TABLE public.custom_offering
TO authenticated;

-- A3. party_capability: approved owner declares and removes active services.
DROP POLICY party_capability_write_own ON public.party_capability;

CREATE POLICY phase32d_party_capability_insert_own
ON public.party_capability
FOR INSERT
TO authenticated
WITH CHECK (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
    AND EXISTS (
        SELECT 1
        FROM public.service_type AS declared_service
        WHERE declared_service.id = party_capability.service_type_id
          AND declared_service.is_active
    )
);

CREATE POLICY phase32d_party_capability_delete_own
ON public.party_capability
FOR DELETE
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
    AND public.current_party_is_approved()
);

REVOKE INSERT, UPDATE ON TABLE public.party_capability
FROM authenticated;

REVOKE INSERT (
    marketplace_party_id,
    service_type_id,
    declared_at
), UPDATE (
    marketplace_party_id,
    service_type_id,
    declared_at
) ON TABLE public.party_capability
FROM authenticated;

GRANT INSERT (
    marketplace_party_id,
    service_type_id,
    declared_at
) ON TABLE public.party_capability
TO authenticated;

-- A3. offer_line_item: only while the owning seller's offer is submitted.
DROP POLICY offer_line_item_write_own ON public.offer_line_item;

CREATE POLICY phase32d_offer_line_item_insert_own
ON public.offer_line_item
FOR INSERT
TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.offer AS parent_offer
        WHERE parent_offer.id = offer_line_item.offer_id
          AND parent_offer.marketplace_party_id =
              public.current_marketplace_party_id()
          AND parent_offer.lifecycle_state =
              'submitted'::public.offer_state
    )
);

CREATE POLICY phase32d_offer_line_item_update_own
ON public.offer_line_item
FOR UPDATE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.offer AS parent_offer
        WHERE parent_offer.id = offer_line_item.offer_id
          AND parent_offer.marketplace_party_id =
              public.current_marketplace_party_id()
          AND parent_offer.lifecycle_state =
              'submitted'::public.offer_state
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.offer AS parent_offer
        WHERE parent_offer.id = offer_line_item.offer_id
          AND parent_offer.marketplace_party_id =
              public.current_marketplace_party_id()
          AND parent_offer.lifecycle_state =
              'submitted'::public.offer_state
    )
);

CREATE POLICY phase32d_offer_line_item_delete_own
ON public.offer_line_item
FOR DELETE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.offer AS parent_offer
        WHERE parent_offer.id = offer_line_item.offer_id
          AND parent_offer.marketplace_party_id =
              public.current_marketplace_party_id()
          AND parent_offer.lifecycle_state =
              'submitted'::public.offer_state
    )
);

REVOKE INSERT, UPDATE ON TABLE public.offer_line_item
FROM authenticated;

REVOKE INSERT (
    id,
    offer_id,
    line_kind,
    product_id,
    item_name,
    specification,
    unit_price,
    quantity,
    line_total,
    display_order
), UPDATE (
    id,
    offer_id,
    line_kind,
    product_id,
    item_name,
    specification,
    unit_price,
    quantity,
    line_total,
    display_order
) ON TABLE public.offer_line_item
FROM authenticated;

GRANT INSERT (
    offer_id,
    line_kind,
    product_id,
    item_name,
    specification,
    unit_price,
    quantity,
    display_order
) ON TABLE public.offer_line_item
TO authenticated;

GRANT UPDATE (
    line_kind,
    product_id,
    item_name,
    specification,
    unit_price,
    quantity,
    display_order
) ON TABLE public.offer_line_item
TO authenticated;

-- A4. design_product_reference: link rows on the caller's own design.
DROP POLICY design_product_reference_write_own
ON public.design_product_reference;

CREATE POLICY phase32d_design_product_reference_insert_own
ON public.design_product_reference
FOR INSERT
TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM public.design AS referenced_design
        WHERE referenced_design.id = design_product_reference.design_id
          AND referenced_design.originating_user_id = auth.uid()
    )
);

CREATE POLICY phase32d_design_product_reference_delete_own
ON public.design_product_reference
FOR DELETE
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.design AS referenced_design
        WHERE referenced_design.id = design_product_reference.design_id
          AND referenced_design.originating_user_id = auth.uid()
    )
);

REVOKE INSERT, UPDATE ON TABLE public.design_product_reference
FROM authenticated;

REVOKE INSERT (
    design_id,
    product_id
), UPDATE (
    design_id,
    product_id
) ON TABLE public.design_product_reference
FROM authenticated;

GRANT INSERT (
    design_id,
    product_id
) ON TABLE public.design_product_reference
TO authenticated;

-- C. service_request: pending-only customer writes, owned address, no party,
-- state changes only through the transition functions below.
DROP POLICY service_request_insert_own ON public.service_request;
DROP POLICY service_request_update_engaged ON public.service_request;

CREATE POLICY phase32d_service_request_insert_own
ON public.service_request
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state = 'pending'::public.service_request_state
    AND marketplace_party_id IS NULL
    AND EXISTS (
        SELECT 1
        FROM public.address AS request_address
        WHERE request_address.id = service_request.address_id
          AND request_address.customer_profile_id =
              public.current_customer_profile_id()
    )
    AND (
        related_order_id IS NULL
        OR EXISTS (
            SELECT 1
            FROM public.purchase_order AS related_order
            WHERE related_order.id = service_request.related_order_id
              AND related_order.customer_profile_id =
                  public.current_customer_profile_id()
        )
    )
);

CREATE POLICY phase32d_service_request_update_own_pending
ON public.service_request
FOR UPDATE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state = 'pending'::public.service_request_state
)
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state = 'pending'::public.service_request_state
    AND marketplace_party_id IS NULL
    AND EXISTS (
        SELECT 1
        FROM public.address AS request_address
        WHERE request_address.id = service_request.address_id
          AND request_address.customer_profile_id =
              public.current_customer_profile_id()
    )
);

REVOKE INSERT, UPDATE ON TABLE public.service_request
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    service_type_id,
    marketplace_party_id,
    address_id,
    related_order_id,
    scheduled_date,
    scheduled_time,
    details,
    price,
    lifecycle_state,
    accepted_at,
    completed_at,
    created_at
), UPDATE (
    id,
    customer_profile_id,
    service_type_id,
    marketplace_party_id,
    address_id,
    related_order_id,
    scheduled_date,
    scheduled_time,
    details,
    price,
    lifecycle_state,
    accepted_at,
    completed_at,
    created_at
) ON TABLE public.service_request
FROM authenticated;

GRANT INSERT (
    customer_profile_id,
    service_type_id,
    address_id,
    related_order_id,
    scheduled_date,
    scheduled_time,
    details
) ON TABLE public.service_request
TO authenticated;

GRANT UPDATE (
    scheduled_date,
    scheduled_time,
    details
) ON TABLE public.service_request
TO authenticated;

CREATE OR REPLACE FUNCTION public.cancel_service_request(
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
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'cancelled'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'pending'
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

ALTER FUNCTION public.cancel_service_request(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.cancel_service_request(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.cancel_service_request(pg_catalog.uuid)
TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.accept_service_request(
    request_id pg_catalog.uuid,
    agreed_price pg_catalog.numeric
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    caller_party pg_catalog.uuid;
    affected_rows pg_catalog.int4;
BEGIN
    IF agreed_price IS NULL OR agreed_price < 0 THEN
        RETURN false;
    END IF;

    SELECT party.id INTO caller_party
    FROM public.marketplace_party AS party
    WHERE party.user_id = auth.uid()
      AND party.approval_state::text = 'approved';

    IF caller_party IS NULL THEN
        RETURN false;
    END IF;

    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'accepted',
        marketplace_party_id = caller_party,
        accepted_at = pg_catalog.now(),
        price = agreed_price
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'pending'
      AND request_row.marketplace_party_id IS NULL
      AND EXISTS (
          SELECT 1
          FROM public.party_capability AS capability
          WHERE capability.marketplace_party_id = caller_party
            AND capability.service_type_id = request_row.service_type_id
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)
TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.start_service_request(
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
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'in_progress'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'accepted'
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = request_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.start_service_request(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.start_service_request(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.start_service_request(pg_catalog.uuid)
TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.complete_service_request(
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
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'completed',
        completed_at = pg_catalog.now()
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'in_progress'
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = request_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.complete_service_request(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.complete_service_request(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.complete_service_request(pg_catalog.uuid)
TO authenticated, service_role;

-- Purchase orders: orders are server-created; the seller edits notes only and
-- advances state through a strict forward map; the customer cancels pending.
DROP POLICY purchase_order_update_party ON public.purchase_order;

CREATE POLICY phase32d_purchase_order_update_party_notes
ON public.purchase_order
FOR UPDATE
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
)
WITH CHECK (
    marketplace_party_id = public.current_marketplace_party_id()
);

REVOKE INSERT, UPDATE ON TABLE public.purchase_order
FROM authenticated;

REVOKE INSERT (
    id,
    customer_profile_id,
    marketplace_party_id,
    address_id,
    origin,
    offer_id,
    custom_offering_id,
    service_request_id,
    settlement_id,
    lifecycle_state,
    order_discount_amount,
    delivery_fee,
    required_upfront_amount,
    notes,
    placed_at,
    cancelled_at,
    ship_recipient_name,
    ship_contact_phone,
    ship_address_line_1,
    ship_address_line_2,
    ship_city,
    ship_country,
    ship_latitude,
    ship_longitude
), UPDATE (
    id,
    customer_profile_id,
    marketplace_party_id,
    address_id,
    origin,
    offer_id,
    custom_offering_id,
    service_request_id,
    settlement_id,
    lifecycle_state,
    order_discount_amount,
    delivery_fee,
    required_upfront_amount,
    notes,
    placed_at,
    cancelled_at,
    ship_recipient_name,
    ship_contact_phone,
    ship_address_line_1,
    ship_address_line_2,
    ship_city,
    ship_country,
    ship_latitude,
    ship_longitude
) ON TABLE public.purchase_order
FROM authenticated;

GRANT UPDATE (
    notes
) ON TABLE public.purchase_order
TO authenticated;

CREATE OR REPLACE FUNCTION public.advance_purchase_order(
    order_id pg_catalog.uuid,
    next_state public.order_state
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
    IF next_state IS NULL THEN
        RETURN false;
    END IF;

    UPDATE "public".purchase_order AS order_row
    SET lifecycle_state = next_state
    WHERE order_row.id = order_id
      AND (order_row.lifecycle_state::text, next_state::text) IN (
          ('pending', 'confirmed'),
          ('confirmed', 'preparing'),
          ('preparing', 'out_for_delivery'),
          ('out_for_delivery', 'delivered')
      )
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = order_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.advance_purchase_order(pg_catalog.uuid, public.order_state)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.advance_purchase_order(pg_catalog.uuid, public.order_state)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.advance_purchase_order(pg_catalog.uuid, public.order_state)
TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.cancel_purchase_order(
    order_id pg_catalog.uuid
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
    UPDATE "public".purchase_order AS order_row
    SET lifecycle_state = 'cancelled',
        cancelled_at = pg_catalog.now()
    WHERE order_row.id = order_id
      AND order_row.lifecycle_state::text = 'pending'
      AND EXISTS (
          SELECT 1
          FROM public.customer_profile AS customer
          WHERE customer.id = order_row.customer_profile_id
            AND customer.user_id = auth.uid()
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

ALTER FUNCTION public.cancel_purchase_order(pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.cancel_purchase_order(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.cancel_purchase_order(pg_catalog.uuid)
TO authenticated, service_role;

-- D1. marketplace_party: public and signed-in readers receive column grants
-- only; RLS policies keep evaluating user_id internally without a grant.
REVOKE SELECT ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

REVOKE SELECT (
    id,
    user_id,
    business_name,
    business_description,
    logo_url,
    coverage_area,
    approval_state,
    state_reason
) ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

GRANT SELECT (
    id,
    business_name,
    business_description,
    logo_url,
    coverage_area,
    approval_state
) ON TABLE public.marketplace_party
TO anon;

GRANT SELECT (
    id,
    business_name,
    business_description,
    logo_url,
    coverage_area,
    approval_state,
    state_reason
) ON TABLE public.marketplace_party
TO authenticated;

DO $phase32d_postflight$
DECLARE
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
BEGIN
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

    -- Exact policy inventory on every touched table.
    IF EXISTS (
        WITH expected(table_name, policy_name, command_name, mode_name, role_list) AS (
            VALUES
                ('address'::name, 'address_select_own_or_engaged'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('address'::name, 'phase32d_address_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('address'::name, 'phase32d_address_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('address'::name, 'phase32d_address_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart'::name, 'phase32d_cart_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart'::name, 'phase32d_cart_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart_line'::name, 'phase32d_cart_line_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart_line'::name, 'phase32d_cart_line_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart_line'::name, 'phase32d_cart_line_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('cart_line'::name, 'phase32d_cart_line_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'custom_offering_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'custom_offering_select_published_or_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'phase32b_custom_offering_anon_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['anon']::name[]),
                ('custom_offering'::name, 'phase32b_custom_offering_anon_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text, ARRAY['anon']::name[]),
                ('custom_offering'::name, 'phase32d_custom_offering_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'phase32d_custom_offering_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('custom_offering'::name, 'phase32d_custom_offering_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('design_product_reference'::name, 'design_product_reference_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('design_product_reference'::name, 'phase32d_design_product_reference_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('design_product_reference'::name, 'phase32d_design_product_reference_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('furnishing_request_design_version'::name, 'furnishing_request_design_version_select'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('furnishing_request_design_version'::name, 'phase32d_furnishing_request_design_version_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('marketplace_party'::name, 'marketplace_party_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('marketplace_party'::name, 'marketplace_party_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('marketplace_party'::name, 'marketplace_party_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('marketplace_party'::name, 'marketplace_party_select_public'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['anon', 'authenticated']::name[]),
                ('marketplace_party'::name, 'marketplace_party_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'offer_line_item_select'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'offer_line_item_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'phase32d_offer_line_item_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'phase32d_offer_line_item_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('offer_line_item'::name, 'phase32d_offer_line_item_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'phase32c_party_capability_admin_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'phase32c_party_capability_anon_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['anon']::name[]),
                ('party_capability'::name, 'phase32c_party_capability_authenticated_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'phase32c_party_capability_owner_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'phase32d_party_capability_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('party_capability'::name, 'phase32d_party_capability_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('purchase_order'::name, 'phase32d_purchase_order_update_party_notes'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('purchase_order'::name, 'purchase_order_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('purchase_order'::name, 'purchase_order_select_engaged'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('review'::name, 'phase32c_review_anon_safe_read'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['anon']::name[]),
                ('review'::name, 'phase32c_review_authenticated_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text, ARRAY['authenticated']::name[]),
                ('review'::name, 'phase32d_review_insert_verified'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('review'::name, 'phase32d_review_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('review'::name, 'review_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('saved_space'::name, 'phase32d_saved_space_delete_own'::name, 'DELETE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('saved_space'::name, 'phase32d_saved_space_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('saved_space'::name, 'phase32d_saved_space_select_own'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('saved_space'::name, 'phase32d_saved_space_update_own'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('service_request'::name, 'phase32d_service_request_insert_own'::name, 'INSERT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('service_request'::name, 'phase32d_service_request_update_own_pending'::name, 'UPDATE'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('service_request'::name, 'service_request_select'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[]),
                ('service_request'::name, 'service_request_select_admin'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['authenticated']::name[])
        ),
        actual AS (
            SELECT
                policy.tablename AS table_name,
                policy.policyname AS policy_name,
                policy.cmd AS command_name,
                policy.permissive AS mode_name,
                policy.roles AS role_list
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.tablename IN (SELECT DISTINCT table_name FROM expected)
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
    ) <> 8 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight policy inventory mismatch';
    END IF;

    -- Every new policy carries its owner anchor and no broadening.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname LIKE 'phase32d\_%'
          AND (
              lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%current_customer_profile_id%'
              AND lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%current_marketplace_party_id%'
              AND lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%originating_user_id = auth.uid()%'
              OR lower(concat_ws(' ', policy.qual, policy.with_check))
                  LIKE '%or true%'
              OR policy.roles <> ARRAY['authenticated']::name[]
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight policy anchor mismatch';
    END IF;

    -- Service-request and review predicates carry their state and ownership
    -- conditions.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND (
              (
                  policy.policyname = 'phase32d_service_request_insert_own'
                  AND (
                      lower(policy.with_check) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%marketplace_party_id is null%'
                      OR lower(policy.with_check) NOT LIKE '%request_address.customer_profile_id%'
                      OR lower(policy.with_check) NOT LIKE '%related_order.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_service_request_update_own_pending'
                  AND (
                      lower(policy.qual) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%marketplace_party_id is null%'
                      OR lower(policy.with_check) NOT LIKE '%request_address.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_review_insert_verified'
                  AND (
                      lower(policy.with_check) NOT LIKE '%''delivered''%'
                      OR lower(policy.with_check) NOT LIKE '%''completed''%'
                      OR lower(policy.with_check) NOT LIKE '%purchased_line.product_id%'
                      OR lower(policy.with_check) NOT LIKE '%reviewed_request.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_address_delete_own'
                  AND (
                      lower(policy.qual) NOT LIKE '%referencing_request.address_id%'
                      OR lower(policy.qual) NOT LIKE '%referencing_service.address_id%'
                      OR lower(policy.qual) NOT LIKE '%referencing_order.address_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_cart_line_insert_own'
                  AND (
                      lower(policy.with_check) NOT LIKE '%stock_quantity > 0%'
                      OR lower(policy.with_check) NOT LIKE '%''published''%'
                      OR lower(policy.with_check) NOT LIKE '%''approved''%'
                      OR lower(policy.with_check) NOT LIKE '%is_active%'
                  )
              )
              OR (
                  policy.policyname LIKE 'phase32d\_custom\_offering\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%current_party_is_approved()%'
              )
              OR (
                  policy.policyname LIKE 'phase32d\_party\_capability\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%current_party_is_approved()%'
              )
              OR (
                  policy.policyname LIKE 'phase32d\_offer\_line\_item\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%''submitted''%'
              )
              OR (
                  policy.policyname = 'phase32d_furnishing_request_design_version_delete_own'
                  AND (
                      lower(policy.qual) NOT LIKE '%''draft''%'
                      OR lower(policy.qual) NOT LIKE '%''open''%'
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight predicate mismatch';
    END IF;

    -- Exact effective privileges after the package.
    IF EXISTS (
        WITH expected(
            table_name,
            column_name,
            role_name,
            table_select,
            table_insert,
            table_update,
            table_delete,
            column_select,
            column_insert,
            column_update
        ) AS (
            VALUES
                ('address'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('address'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('address'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'label'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'label'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'label'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'recipient_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'recipient_name'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'recipient_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'contact_phone'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'contact_phone'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'contact_phone'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_1'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'address_line_1'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'address_line_1'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'address_line_2'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'address_line_2'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'address_line_2'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'city'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'city'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'city'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'country'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'country'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'country'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'latitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'latitude'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'latitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'longitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'longitude'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'longitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('address'::name, 'is_default'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('address'::name, 'is_default'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('address'::name, 'is_default'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('cart'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('cart'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('cart_line'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'cart_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'cart_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('cart_line'::name, 'cart_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'product_color_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'product_color_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('cart_line'::name, 'product_color_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('cart_line'::name, 'quantity'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('cart_line'::name, 'quantity'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('cart_line'::name, 'quantity'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('saved_space'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('saved_space'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'space_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'space_name'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('saved_space'::name, 'space_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'width_cm'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'width_cm'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('saved_space'::name, 'width_cm'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'depth_cm'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'depth_cm'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('saved_space'::name, 'depth_cm'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('saved_space'::name, 'measurement_source'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('saved_space'::name, 'measurement_source'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('saved_space'::name, 'measurement_source'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('review'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('review'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_kind'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_kind'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'target_kind'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_product_id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_product_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'target_product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_service_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('review'::name, 'target_service_request_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'target_service_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'target_marketplace_party_id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'target_marketplace_party_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'target_marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'rating'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'rating'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'rating'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'comment'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'comment'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('review'::name, 'comment'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('review'::name, 'created_at'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('review'::name, 'created_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('review'::name, 'created_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('furnishing_request_design_version'::name, 'furnishing_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('furnishing_request_design_version'::name, 'design_version_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('custom_offering'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('custom_offering'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'design_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'design_id'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'design_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_price'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'published_price'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'published_price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'title'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'title'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'title'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'description'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'description'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'description'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'publication_state'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'publication_state'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'publication_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('custom_offering'::name, 'published_at'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('custom_offering'::name, 'published_at'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('custom_offering'::name, 'published_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'marketplace_party_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('party_capability'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'service_type_id'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'service_type_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('party_capability'::name, 'service_type_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('party_capability'::name, 'declared_at'::name, 'anon'::text, true, false, false, false, true, false, false),
                ('party_capability'::name, 'declared_at'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('party_capability'::name, 'declared_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('offer_line_item'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'offer_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'offer_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('offer_line_item'::name, 'offer_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_kind'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'line_kind'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'line_kind'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'product_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'product_id'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'item_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'item_name'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'item_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'specification'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'specification'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'specification'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'unit_price'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'unit_price'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'unit_price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'quantity'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'quantity'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'quantity'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'line_total'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'line_total'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('offer_line_item'::name, 'line_total'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('offer_line_item'::name, 'display_order'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('offer_line_item'::name, 'display_order'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('offer_line_item'::name, 'display_order'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'design_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('design_product_reference'::name, 'design_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('design_product_reference'::name, 'design_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('design_product_reference'::name, 'product_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('design_product_reference'::name, 'product_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('design_product_reference'::name, 'product_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('service_request'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'service_type_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'service_type_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('service_request'::name, 'service_type_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'marketplace_party_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'address_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'address_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('service_request'::name, 'address_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'related_order_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'related_order_id'::name, 'authenticated'::text, true, false, false, true, true, true, false),
                ('service_request'::name, 'related_order_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'scheduled_date'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'scheduled_date'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('service_request'::name, 'scheduled_date'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'scheduled_time'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'scheduled_time'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('service_request'::name, 'scheduled_time'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'details'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'details'::name, 'authenticated'::text, true, false, false, true, true, true, true),
                ('service_request'::name, 'details'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'price'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'price'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'price'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'lifecycle_state'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'lifecycle_state'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'lifecycle_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'accepted_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'accepted_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'accepted_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'completed_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'completed_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'completed_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('service_request'::name, 'created_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('service_request'::name, 'created_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('service_request'::name, 'created_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'customer_profile_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'customer_profile_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'customer_profile_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'marketplace_party_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'address_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'address_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'address_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'origin'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'origin'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'origin'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'offer_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'offer_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'offer_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'custom_offering_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'custom_offering_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'custom_offering_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'service_request_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'service_request_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'service_request_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'settlement_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'settlement_id'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'settlement_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'lifecycle_state'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'lifecycle_state'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'lifecycle_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'order_discount_amount'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'order_discount_amount'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'order_discount_amount'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'delivery_fee'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'delivery_fee'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'delivery_fee'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'required_upfront_amount'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'notes'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'notes'::name, 'authenticated'::text, true, false, false, true, true, false, true),
                ('purchase_order'::name, 'notes'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'placed_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'placed_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'placed_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'cancelled_at'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'cancelled_at'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'cancelled_at'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_recipient_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_contact_phone'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_address_line_1'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_address_line_2'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_city'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_city'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_city'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_country'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_country'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_country'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_latitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_latitude'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_latitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('purchase_order'::name, 'ship_longitude'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('purchase_order'::name, 'ship_longitude'::name, 'authenticated'::text, true, false, false, true, true, false, false),
                ('purchase_order'::name, 'ship_longitude'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'id'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'id'::name, 'authenticated'::text, false, false, false, true, true, false, false),
                ('marketplace_party'::name, 'id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'user_id'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('marketplace_party'::name, 'user_id'::name, 'authenticated'::text, false, false, false, true, false, true, false),
                ('marketplace_party'::name, 'user_id'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'business_name'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'business_name'::name, 'authenticated'::text, false, false, false, true, true, true, true),
                ('marketplace_party'::name, 'business_name'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'business_description'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'business_description'::name, 'authenticated'::text, false, false, false, true, true, true, true),
                ('marketplace_party'::name, 'business_description'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'logo_url'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'logo_url'::name, 'authenticated'::text, false, false, false, true, true, true, true),
                ('marketplace_party'::name, 'logo_url'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'coverage_area'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'coverage_area'::name, 'authenticated'::text, false, false, false, true, true, true, true),
                ('marketplace_party'::name, 'coverage_area'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'approval_state'::name, 'anon'::text, false, false, false, false, true, false, false),
                ('marketplace_party'::name, 'approval_state'::name, 'authenticated'::text, false, false, false, true, true, false, false),
                ('marketplace_party'::name, 'approval_state'::name, 'service_role'::text, true, true, true, true, true, true, true),
                ('marketplace_party'::name, 'state_reason'::name, 'anon'::text, false, false, false, false, false, false, false),
                ('marketplace_party'::name, 'state_reason'::name, 'authenticated'::text, false, false, false, true, true, false, false),
                ('marketplace_party'::name, 'state_reason'::name, 'service_role'::text, true, true, true, true, true, true, true)
        ),
        roles(role_name, role_oid) AS (
            VALUES
                ('anon'::text, anon_role_oid),
                ('authenticated'::text, authenticated_role_oid),
                ('service_role'::text, service_role_oid)
        )
        SELECT 1
        FROM expected
        JOIN roles ON roles.role_name = expected.role_name
        CROSS JOIN LATERAL (
            SELECT
                pg_catalog.to_regclass('public.' || expected.table_name)
                    AS table_oid
        ) AS target
        WHERE target.table_oid IS NULL
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'SELECT')
              IS DISTINCT FROM expected.table_select
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'INSERT')
              IS DISTINCT FROM expected.table_insert
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'UPDATE')
              IS DISTINCT FROM expected.table_update
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'DELETE')
              IS DISTINCT FROM expected.table_delete
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'SELECT'
              ) IS DISTINCT FROM expected.column_select
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'INSERT'
              ) IS DISTINCT FROM expected.column_insert
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'UPDATE'
              ) IS DISTINCT FROM expected.column_update
    ) OR EXISTS (
        -- No column ACL entry may carry the grant option or name PUBLIC (0).
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            attribute.attacl
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (

              'address',
              'cart',
              'cart_line',
              'saved_space',
              'review',
              'furnishing_request_design_version',
              'custom_offering',
              'party_capability',
              'offer_line_item',
              'design_product_reference',
              'service_request',
              'purchase_order',
              'marketplace_party'
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND (acl.is_grantable OR acl.grantee = 0)
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight privilege mismatch';
    END IF;

    -- Transition functions: exact metadata, direction, ownership, and grants.
    IF EXISTS (
        WITH expected(signature, old_state, new_state, forbidden_states) AS (
            VALUES
                ('public.cancel_service_request(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['accepted', 'in_progress', 'completed']::text[]),
                ('public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)'::text, 'pending'::text, 'accepted'::text, ARRAY['in_progress', 'completed', 'cancelled']::text[]),
                ('public.start_service_request(pg_catalog.uuid)'::text, 'accepted'::text, 'in_progress'::text, ARRAY['pending', 'completed', 'cancelled']::text[]),
                ('public.complete_service_request(pg_catalog.uuid)'::text, 'in_progress'::text, 'completed'::text, ARRAY['pending', 'accepted', 'cancelled']::text[]),
                ('public.cancel_purchase_order(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['confirmed', 'preparing', 'out_for_delivery', 'delivered']::text[]),
                ('public.advance_purchase_order(pg_catalog.uuid, public.order_state)'::text, 'pending'::text, 'confirmed'::text, ARRAY['cancelled']::text[])
        )
        SELECT 1
        FROM expected
        LEFT JOIN pg_catalog.pg_proc AS function_metadata
            ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
        WHERE function_metadata.oid IS NULL
           OR function_metadata.prorettype <> 'pg_catalog.bool'::pg_catalog.regtype
           OR function_metadata.prolang <> (
                  SELECT language.oid
                  FROM pg_catalog.pg_language AS language
                  WHERE language.lanname = 'plpgsql'
              )
           OR function_metadata.provolatile <> 'v'::pg_catalog."char"
           OR NOT function_metadata.prosecdef
           OR function_metadata.proowner <> postgres_role_oid
           OR coalesce(function_metadata.proconfig NOT IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[]), true)
           OR lower(function_metadata.prosrc) NOT LIKE '%auth.uid()%'
           -- advance_purchase_order lists its allowed (from, to) pairs rather
           -- than testing one state, so it is checked for its first pair.
           OR lower(function_metadata.prosrc) NOT LIKE
                  CASE
                      WHEN expected.signature LIKE 'public.advance\_purchase\_order(%'
                      THEN '%(''' || expected.old_state || ''', '''
                           || expected.new_state || ''')%'
                      ELSE '%lifecycle_state::text = ''' || expected.old_state || '''%'
                  END
           OR lower(function_metadata.prosrc) NOT LIKE '%''' || expected.new_state || '''%'
           OR lower(function_metadata.prosrc) LIKE '%or true%'
           OR lower(function_metadata.prosrc) NOT LIKE '%get diagnostics affected_rows = row_count%'
           OR lower(function_metadata.prosrc) NOT LIKE '%return affected_rows = 1%'
           OR EXISTS (
                  SELECT 1
                  FROM unnest(expected.forbidden_states) AS forbidden(state_name)
                  WHERE lower(function_metadata.prosrc)
                      LIKE '%''' || forbidden.state_name || '''%'
              )
           OR pg_catalog.has_function_privilege(anon_role_oid, function_metadata.oid, 'EXECUTE')
           OR NOT pg_catalog.has_function_privilege(
                  authenticated_role_oid, function_metadata.oid, 'EXECUTE'
              )
           OR NOT pg_catalog.has_function_privilege(
                  service_role_oid, function_metadata.oid, 'EXECUTE'
              )
           OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.aclexplode(
                      COALESCE(
                          function_metadata.proacl,
                          pg_catalog.acldefault('f'::pg_catalog."char", function_metadata.proowner)
                      )
                  ) AS acl
                  WHERE acl.privilege_type = 'EXECUTE'
                    AND (
                        acl.grantee NOT IN (
                            postgres_role_oid,
                            authenticated_role_oid,
                            service_role_oid
                        )
                        OR (
                            acl.grantee IN (authenticated_role_oid, service_role_oid)
                            AND acl.is_grantable
                        )
                    )
              )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight transition function mismatch';
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
            MESSAGE = 'Phase 3.2D postflight RLS/FORCE mismatch';
    END IF;
END
$phase32d_postflight$;

COMMIT;
