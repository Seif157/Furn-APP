/* Phase 3.2B core preflight-only artifact.
Generated mechanically from the core migration safeguards and exact preflight.
It performs no migration DDL/DCL and always rolls back. Review required. */
BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

-- Every preflight check runs before the first DDL/DCL statement. Any drift or
-- timeout aborts this transaction before security state can change.
DO $phase32b_preflight$
DECLARE
    required_role text;
    required_column text;
    insert_policy_count integer;
    insert_policy record;
    helper_function_name text;
    helper_function_count integer;
    expected_helper_source text;
    actual_helper_source text;
    current_role_is_superuser boolean;
    can_manage_defaults boolean;
    authenticated_role_oid oid;
    anon_role_oid oid;
    service_role_oid oid;
    missing_tables text;
    unexpected_tables text;
    policy_expectation record;
    actual_policy record;
    policy_count integer;
    normalized_policy_expression text;
    canonical_policy_expression text;
    boolean_prefix text;
    and_operator_position integer;
    or_operator_position integer;
    and_operator_depth integer;
    or_operator_depth integer;
    write_expectation record;
    default_expectation record;
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
            MESSAGE = 'Phase 3.2B requires PostgreSQL 15 or newer';
    END IF;

    -- Fail closed on the live enum inventory before any policy expression is
    -- inspected. Build the known-absent legacy name in two pieces so static
    -- guards can reject that identifier everywhere else in this package.
    IF pg_catalog.to_regtype('public.product_state') IS NULL
       OR pg_catalog.to_regtype('public.custom_offering_state') IS NULL
       OR pg_catalog.to_regtype('public.party_approval_state') IS NULL
       OR pg_catalog.to_regtype(
           pg_catalog.format('public.product_%s_state', 'lifecycle')
       ) IS NOT NULL
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B required enum inventory drift';
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
                MESSAGE = format('Phase 3.2B missing required role: %s', required_role);
        END IF;
    END LOOP;

    WITH expected(table_name) AS (
        SELECT unnest(expected_tables)
    ),
    actual(table_name) AS (
        SELECT relation.relname::text
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p')
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
            MESSAGE = format(
                'Phase 3.2B public base-table inventory drift; missing=[%s]; unexpected=[%s]',
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
          AND relation.relkind IN ('r', 'p')
          AND NOT relation.relrowsecurity
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B requires RLS on every public base table';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'order_financial_position'
          AND relation.relkind = 'v'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B expected public.order_financial_position view';
    END IF;

    SELECT role_row.oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'anon';

    SELECT role_row.oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'authenticated';

    SELECT role_row.oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'service_role';

    IF pg_catalog.pg_has_role(
        anon_role_oid,
        service_role_oid,
        'MEMBER'
    ) OR pg_catalog.pg_has_role(
        authenticated_role_oid,
        service_role_oid,
        'MEMBER'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B client role must not inherit or assume service_role';
    END IF;

    FOREACH required_column IN ARRAY ARRAY[
        'id',
        'user_id',
        'business_name',
        'business_description',
        'logo_url',
        'coverage_area',
        'approval_state',
        'state_reason'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = 'public.marketplace_party'::regclass
              AND attribute.attname = required_column
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B missing marketplace_party column: %s',
                    required_column
                );
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attrdef AS default_row
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = default_row.adrelid
           AND attribute.attnum = default_row.adnum
        WHERE default_row.adrelid = 'public.marketplace_party'::regclass
          AND attribute.attname = 'id'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B requires the generated marketplace_party.id default';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attrdef AS default_row
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = default_row.adrelid
           AND attribute.attnum = default_row.adnum
        WHERE default_row.adrelid = 'public.marketplace_party'::regclass
          AND attribute.attname = 'approval_state'
          AND pg_catalog.pg_get_expr(
              default_row.adbin,
              default_row.adrelid,
              true
          ) ~* 'pending'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B requires marketplace_party.approval_state to default to pending';
    END IF;

    SELECT count(*)
    INTO insert_policy_count
    FROM pg_catalog.pg_policy AS policy
    WHERE policy.polrelid = 'public.marketplace_party'::regclass
      AND policy.polcmd = 'a'::pg_catalog."char";

    IF insert_policy_count <> 1 THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B expected one authenticated marketplace_party INSERT policy; found %s',
                insert_policy_count
            );
    END IF;

    SELECT
        policy.polname,
        policy.polcmd,
        policy.polpermissive,
        policy.polroles,
        pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true) AS using_expr,
        pg_catalog.pg_get_expr(
            policy.polwithcheck,
            policy.polrelid,
            true
        ) AS check_expr
    INTO STRICT insert_policy
    FROM pg_catalog.pg_policy AS policy
    WHERE policy.polrelid = 'public.marketplace_party'::regclass
      AND policy.polcmd = 'a'::pg_catalog."char";

    IF insert_policy.polcmd <> 'a'::pg_catalog."char"
       OR NOT insert_policy.polpermissive
       OR NOT (
           insert_policy.polroles @> ARRAY[authenticated_role_oid]::oid[]
           AND insert_policy.polroles <@ ARRAY[authenticated_role_oid]::oid[]
       )
       OR insert_policy.using_expr IS NOT NULL
       OR insert_policy.check_expr IS NULL
       OR insert_policy.check_expr !~* 'user_id.*auth\.uid'
       OR insert_policy.check_expr ~* 'approval_state|state_reason'
    THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B marketplace_party INSERT policy drift: %s',
                insert_policy.polname
            );
    END IF;

    -- Exact audited client write shape before normalization.
    IF NOT pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.marketplace_party'::regclass,
        'INSERT'
    )
       OR NOT pg_catalog.has_table_privilege(
           anon_role_oid,
           'public.marketplace_party'::regclass,
           'UPDATE'
       )
       OR NOT pg_catalog.has_table_privilege(
           anon_role_oid,
           'public.marketplace_party'::regclass,
           'DELETE'
       )
       OR NOT pg_catalog.has_table_privilege(
           authenticated_role_oid,
           'public.marketplace_party'::regclass,
           'INSERT'
       )
       OR pg_catalog.has_table_privilege(
           authenticated_role_oid,
           'public.marketplace_party'::regclass,
           'UPDATE'
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B marketplace_party table privilege drift detected';
    END IF;

    IF EXISTS (
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
        WHERE relation.oid = 'public.marketplace_party'::regclass
          AND acl.grantee = 0
          AND acl.privilege_type IN ('INSERT', 'UPDATE')
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B marketplace_party PUBLIC write privilege drift detected';
    END IF;

    FOR required_column IN
        SELECT column_name
        FROM unnest(ARRAY[
            'id',
            'user_id',
            'business_name',
            'business_description',
            'logo_url',
            'coverage_area',
            'approval_state',
            'state_reason'
        ]) AS columns(column_name)
    LOOP
        IF NOT pg_catalog.has_column_privilege(
            authenticated_role_oid,
            'public.marketplace_party'::regclass,
            required_column,
            'INSERT'
        )
           OR (
               pg_catalog.has_column_privilege(
                   authenticated_role_oid,
                   'public.marketplace_party'::regclass,
                   required_column,
                   'UPDATE'
               ) IS DISTINCT FROM (
                   required_column = ANY(ARRAY[
                       'business_name',
                       'business_description',
                       'logo_url',
                       'coverage_area'
                   ])
               )
           )
        THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B marketplace_party column privilege drift: %s',
                    required_column
                );
        END IF;
    END LOOP;

    IF NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.marketplace_party'::regclass,
        'INSERT'
    )
       OR NOT pg_catalog.has_table_privilege(
           service_role_oid,
           'public.marketplace_party'::regclass,
           'UPDATE'
       )
       OR NOT pg_catalog.has_table_privilege(
           service_role_oid,
           'public.marketplace_party'::regclass,
           'DELETE'
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B service_role marketplace_party privilege drift detected';
    END IF;

    -- The audited financial view is postgres-owned, owner-rights, and directly
    -- selectable by exactly the three Supabase API roles before hardening.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        WHERE relation.oid = 'public.order_financial_position'::regclass
          AND pg_catalog.pg_get_userbyid(relation.relowner) = 'postgres'
          AND NOT COALESCE(
              relation.reloptions @> ARRAY['security_invoker=true'],
              false
          )
          AND pg_catalog.has_table_privilege(anon_role_oid, relation.oid, 'SELECT')
          AND pg_catalog.has_table_privilege(
              authenticated_role_oid,
              relation.oid,
              'SELECT'
          )
          AND pg_catalog.has_table_privilege(
              service_role_oid,
              relation.oid,
              'SELECT'
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B financial view metadata or effective grant drift detected';
    END IF;

    WITH actual_grantees AS (
        SELECT CASE
            WHEN acl.grantee = 0 THEN 'PUBLIC'
            ELSE grantee.rolname
        END AS grantee_name
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
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE relation.oid = 'public.order_financial_position'::regclass
          AND acl.privilege_type = 'SELECT'
          AND acl.grantee <> relation.relowner
    ),
    expected_grantees(grantee_name) AS (
        VALUES ('anon'::name), ('authenticated'::name), ('service_role'::name)
    ),
    missing AS (
        SELECT grantee_name FROM expected_grantees
        EXCEPT
        SELECT grantee_name FROM actual_grantees
    ),
    unexpected AS (
        SELECT grantee_name FROM actual_grantees
        EXCEPT
        SELECT grantee_name FROM expected_grantees
    )
    SELECT
        (SELECT string_agg(grantee_name, ', ' ORDER BY grantee_name) FROM missing),
        (SELECT string_agg(grantee_name, ', ' ORDER BY grantee_name) FROM unexpected)
    INTO missing_tables, unexpected_tables;

    IF missing_tables IS NOT NULL OR unexpected_tables IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B financial view SELECT grant drift; missing=[%s]; unexpected=[%s]',
                COALESCE(missing_tables, 'none'),
                COALESCE(unexpected_tables, 'none')
            );
    END IF;

    -- Validate the six Phase 3.2A mixed policies by catalog identity, complete
    -- Boolean/operator semantics, and authorization dependencies. pg_get_expr()
    -- reconstructs SQL, so alias and qualification changes are canonicalized;
    -- grouping is checked independently instead of ignored.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
            (
                'custom_offering'::name,
                'custom_offering_select_published_or_own'::name,
                $canonical$publication_state='published'::custom_offering_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.custom_offering_state'::text,
                false
            ),
            (
                'product'::name,
                'product_select_published_or_own'::name,
                $canonical$lifecycle_state='published'::product_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.product_state'::text,
                false
            ),
            (
                'product_color'::name,
                'product_color_select'::name,
                $canonical$existsselect1fromproductwhereid=product_idandlifecycle_state='published'::product_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.product_state'::text,
                true
            ),
            (
                'product_image'::name,
                'product_image_select'::name,
                $canonical$existsselect1fromproductwhereid=product_idandlifecycle_state='published'::product_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.product_state'::text,
                true
            ),
            (
                'product_3d_model'::name,
                'product_3d_model_select'::name,
                $canonical$existsselect1fromproductwhereid=product_idandlifecycle_state='published'::product_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.product_state'::text,
                true
            ),
            (
                'product_enrichment_assignment'::name,
                'product_enrichment_assignment_select'::name,
                $canonical$existsselect1fromproductwhereid=product_idandlifecycle_state='published'::product_stateormarketplace_party_id=current_marketplace_party_id$canonical$::text,
                'public.product_state'::text,
                true
            )
        ) AS expected(
            table_name,
            policy_name,
            expected_canonical_expression,
            expected_state_type,
            is_product_child
        )
    LOOP
        SELECT count(*)
        INTO policy_count
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = policy_expectation.table_name
          AND policy.polname = policy_expectation.policy_name;

        IF policy_count <> 1 THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B required policy count drift: public.%s.%s found=%s',
                    policy_expectation.table_name,
                    policy_expectation.policy_name,
                    policy_count
                );
        END IF;

        SELECT
            policy.oid AS policy_oid,
            policy.polcmd,
            policy.polpermissive,
            policy.polroles,
            pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true)
                AS using_expr,
            pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true)
                AS check_expr
        INTO STRICT actual_policy
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relname = policy_expectation.table_name
          AND policy.polname = policy_expectation.policy_name;

        normalized_policy_expression := pg_catalog.regexp_replace(
            lower(actual_policy.using_expr),
            '[[:space:]]+',
            ' ',
            'g'
        );
        canonical_policy_expression := normalized_policy_expression;
        IF policy_expectation.is_product_child THEN
            canonical_policy_expression := pg_catalog.regexp_replace(
                canonical_policy_expression,
                'from[[:space:]]+(public\.)?product([[:space:]]+as)?[[:space:]]+[a-z_][a-z0-9_]*[[:space:]]+where',
                'from product where',
                'g'
            );
        END IF;
        canonical_policy_expression := pg_catalog.regexp_replace(
            canonical_policy_expression,
            '\m[a-z_][a-z0-9_]*\.',
            '',
            'g'
        );
        canonical_policy_expression := pg_catalog.regexp_replace(
            canonical_policy_expression,
            '[[:space:]()]',
            '',
            'g'
        );
        IF policy_expectation.is_product_child THEN
            and_operator_position := position(
                ' and ' IN normalized_policy_expression
            );
            or_operator_position := position(
                ' or ' IN normalized_policy_expression
            );
            IF and_operator_position > 0 AND or_operator_position > 0 THEN
                boolean_prefix := substring(
                    normalized_policy_expression
                    FROM 1 FOR and_operator_position - 1
                );
                and_operator_depth :=
                    length(boolean_prefix)
                    - length(replace(boolean_prefix, '(', ''))
                    - length(boolean_prefix)
                    + length(replace(boolean_prefix, ')', ''));
                boolean_prefix := substring(
                    normalized_policy_expression
                    FROM 1 FOR or_operator_position - 1
                );
                or_operator_depth :=
                    length(boolean_prefix)
                    - length(replace(boolean_prefix, '(', ''))
                    - length(boolean_prefix)
                    + length(replace(boolean_prefix, ')', ''));
            ELSE
                and_operator_depth := -1;
                or_operator_depth := -1;
            END IF;
        ELSE
            and_operator_position := position(
                ' and ' IN normalized_policy_expression
            );
            or_operator_position := position(
                ' or ' IN normalized_policy_expression
            );
            and_operator_depth := NULL;
            or_operator_depth := NULL;
        END IF;

        IF actual_policy.polcmd <> 'r'::pg_catalog."char"
           OR NOT actual_policy.polpermissive
           OR NOT (
               actual_policy.polroles @>
                   ARRAY[anon_role_oid, authenticated_role_oid]::oid[]
               AND actual_policy.polroles <@
                   ARRAY[anon_role_oid, authenticated_role_oid]::oid[]
           )
           OR actual_policy.check_expr IS NOT NULL
           OR actual_policy.using_expr IS NULL
           OR canonical_policy_expression IS DISTINCT FROM
               policy_expectation.expected_canonical_expression
           OR or_operator_position = 0
           OR (
               policy_expectation.is_product_child
               AND (
                   and_operator_position = 0
                   OR or_operator_depth <= and_operator_depth
               )
           )
           OR (
               NOT policy_expectation.is_product_child
               AND and_operator_position > 0
           )
           OR position('is_admin' IN lower(actual_policy.using_expr)) > 0
           OR NOT EXISTS (
               SELECT 1
               FROM pg_catalog.pg_depend AS dependency
               WHERE dependency.classid = 'pg_catalog.pg_policy'::regclass
                 AND dependency.objid = actual_policy.policy_oid
                 AND dependency.refclassid = 'pg_catalog.pg_proc'::regclass
                 AND dependency.refobjid =
                     'public.current_marketplace_party_id()'::regprocedure
           )
           OR NOT EXISTS (
               SELECT 1
               FROM pg_catalog.pg_depend AS dependency
               WHERE dependency.classid = 'pg_catalog.pg_policy'::regclass
                 AND dependency.objid = actual_policy.policy_oid
                 AND dependency.refclassid = 'pg_catalog.pg_type'::regclass
                 AND dependency.refobjid = pg_catalog.to_regtype(
                     policy_expectation.expected_state_type
                 )::oid
           )
           OR EXISTS (
               SELECT 1
               FROM pg_catalog.pg_depend AS dependency
               WHERE dependency.classid = 'pg_catalog.pg_policy'::regclass
                 AND dependency.objid = actual_policy.policy_oid
                 AND dependency.refclassid = 'pg_catalog.pg_proc'::regclass
                 AND dependency.refobjid = 'public.is_admin()'::regprocedure
           )
           OR (
               policy_expectation.is_product_child
               AND NOT EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_depend AS dependency
                   WHERE dependency.classid = 'pg_catalog.pg_policy'::regclass
                     AND dependency.objid = actual_policy.policy_oid
                     AND dependency.refclassid = 'pg_catalog.pg_class'::regclass
                     AND dependency.refobjid = 'public.product'::regclass
               )
           )
        THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B required policy metadata drift: public.%s.%s',
                    policy_expectation.table_name,
                    policy_expectation.policy_name
                );
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        WHERE relation.relnamespace = 'public'::regnamespace
          AND policy.polname LIKE 'phase32b\_%' ESCAPE '\'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B policy artifacts already exist';
    END IF;

    -- A restrictive write policy cannot grant access. Confirm a permissive,
    -- authenticated seller policy remains applicable to every guarded operation.
    FOR write_expectation IN
        SELECT *
        FROM (VALUES
            ('product_color'::name, 'a'::pg_catalog."char"),
            ('product_color'::name, 'w'::pg_catalog."char"),
            ('product_color'::name, 'd'::pg_catalog."char"),
            ('product_image'::name, 'a'::pg_catalog."char"),
            ('product_image'::name, 'w'::pg_catalog."char"),
            ('product_image'::name, 'd'::pg_catalog."char"),
            ('product_3d_model'::name, 'a'::pg_catalog."char"),
            ('product_3d_model'::name, 'w'::pg_catalog."char"),
            ('product_3d_model'::name, 'd'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'a'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'w'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'd'::pg_catalog."char")
        ) AS expected(table_name, policy_command)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
            WHERE relation.relnamespace = 'public'::regnamespace
              AND relation.relname = write_expectation.table_name
              AND policy.polpermissive
              AND policy.polcmd IN (
                  '*'::pg_catalog."char",
                  write_expectation.policy_command
              )
              AND (
                  0 = ANY(policy.polroles)
                  OR authenticated_role_oid = ANY(policy.polroles)
              )
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
                  pg_catalog.pg_get_expr(
                      policy.polwithcheck,
                      policy.polrelid,
                      true
                  )
              )) ~ 'current_marketplace_party_id'
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B missing permissive seller-write path: public.%s command=%s',
                    write_expectation.table_name,
                    write_expectation.policy_command
                );
        END IF;
    END LOOP;

    FOREACH helper_function_name IN ARRAY ARRAY[
        'is_admin',
        'current_marketplace_party_id',
        'current_party_is_approved'
    ]
    LOOP
        SELECT count(*)
        INTO helper_function_count
        FROM pg_catalog.pg_proc AS function_row
        WHERE function_row.pronamespace = 'public'::regnamespace
          AND function_row.proname = helper_function_name;

        IF helper_function_count <> 1 THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B expected one public.%s overload; found %s',
                    helper_function_name,
                    helper_function_count
                );
        END IF;

        expected_helper_source := CASE helper_function_name
            WHEN 'is_admin' THEN
                'select exists ( select 1 from public.admin_user a where a.user_id = auth.uid() and a.is_active )'
            WHEN 'current_marketplace_party_id' THEN
                'select mp.id from public.marketplace_party mp where mp.user_id = auth.uid()'
            WHEN 'current_party_is_approved' THEN
                'select exists ( select 1 from public.marketplace_party mp where mp.user_id = auth.uid() and mp.approval_state = ''approved'' )'
        END;

        expected_helper_source := btrim(
            pg_catalog.regexp_replace(
                lower(expected_helper_source),
                '[[:space:]]',
                '',
                'g'
            ),
            ';'
        );

        SELECT btrim(
            pg_catalog.regexp_replace(
                lower(function_row.prosrc),
                '[[:space:]]',
                '',
                'g'
            ),
            ';'
        )
        INTO STRICT actual_helper_source
        FROM pg_catalog.pg_proc AS function_row
        WHERE function_row.pronamespace = 'public'::regnamespace
          AND function_row.proname = helper_function_name;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS function_row
            JOIN pg_catalog.pg_language AS language_row
                ON language_row.oid = function_row.prolang
            WHERE function_row.pronamespace = 'public'::regnamespace
              AND function_row.proname = helper_function_name
              AND function_row.pronargs = 0
              AND function_row.prokind = 'f'
              AND function_row.provolatile = 's'
              AND function_row.prosecdef
              AND language_row.lanname = 'sql'
              AND pg_catalog.pg_get_userbyid(function_row.proowner) = 'postgres'
              AND function_row.prorettype = CASE helper_function_name
                  WHEN 'current_marketplace_party_id' THEN 'uuid'::regtype
                  ELSE 'boolean'::regtype
              END
              AND pg_catalog.cardinality(function_row.proconfig) = 1
              AND EXISTS (
                  SELECT 1
                  FROM unnest(function_row.proconfig) AS setting
                  WHERE pg_catalog.regexp_replace(
                      setting,
                      '["[:space:]]',
                      '',
                      'g'
                  ) = 'search_path=public,pg_temp'
              )
        )
           OR actual_helper_source IS DISTINCT FROM expected_helper_source
        THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B helper definition or security metadata drift: public.%s',
                    helper_function_name
                );
        END IF;
    END LOOP;

    -- The first audit hid non-public schema defaults. Compare the reviewed
    -- Supabase-managed storage signature as an exact metadata set. Owner ACL
    -- entries are intrinsic and excluded; every other storage grantee is part
    -- of the comparison. MAINTAIN is metadata text here, so PostgreSQL 15 can
    -- parse this block even though only PostgreSQL 17+ expects that row.
    WITH expected_storage_signature(
        owner_name,
        schema_name,
        object_type,
        grantee_name,
        privilege_type,
        is_grantable
    ) AS (
        SELECT
            'postgres'::name,
            'storage'::name,
            privilege.object_type,
            grantee.grantee_name,
            privilege.privilege_type,
            false
        FROM (VALUES
            ('anon'::name),
            ('authenticated'::name),
            ('service_role'::name)
        ) AS grantee(grantee_name)
        CROSS JOIN (VALUES
            ('r'::pg_catalog."char", 'SELECT'::text),
            ('r'::pg_catalog."char", 'INSERT'::text),
            ('r'::pg_catalog."char", 'UPDATE'::text),
            ('r'::pg_catalog."char", 'DELETE'::text),
            ('r'::pg_catalog."char", 'TRUNCATE'::text),
            ('r'::pg_catalog."char", 'REFERENCES'::text),
            ('r'::pg_catalog."char", 'TRIGGER'::text),
            ('r'::pg_catalog."char", 'MAINTAIN'::text),
            ('S'::pg_catalog."char", 'SELECT'::text),
            ('S'::pg_catalog."char", 'UPDATE'::text),
            ('S'::pg_catalog."char", 'USAGE'::text),
            ('f'::pg_catalog."char", 'EXECUTE'::text)
        ) AS privilege(object_type, privilege_type)
        WHERE privilege.privilege_type <> 'MAINTAIN'
           OR current_setting('server_version_num')::integer >= 170000
    ),
    actual_storage_signature AS (
        SELECT
            owner_role.rolname AS owner_name,
            namespace.nspname AS schema_name,
            defaults.defaclobjtype AS object_type,
            CASE WHEN acl.grantee = 0 THEN 'PUBLIC'::name
                ELSE grantee_role.rolname
            END AS grantee_name,
            acl.privilege_type,
            acl.is_grantable
        FROM pg_catalog.pg_default_acl AS defaults
        JOIN pg_catalog.pg_roles AS owner_role
            ON owner_role.oid = defaults.defaclrole
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = defaults.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
            ON grantee_role.oid = acl.grantee
        WHERE namespace.nspname = 'storage'
          AND acl.grantee <> defaults.defaclrole
    ),
    missing AS (
        SELECT * FROM expected_storage_signature
        EXCEPT
        SELECT * FROM actual_storage_signature
    ),
    unexpected AS (
        SELECT * FROM actual_storage_signature
        EXCEPT
        SELECT * FROM expected_storage_signature
    )
    SELECT
        (
            SELECT string_agg(
                format(
                    '%s:%s:%s:%s:%s:grantable=%s',
                    owner_name,
                    schema_name,
                    object_type,
                    grantee_name,
                    privilege_type,
                    is_grantable
                ),
                ', ' ORDER BY owner_name, schema_name, object_type,
                grantee_name, privilege_type, is_grantable
            )
            FROM missing
        ),
        (
            SELECT string_agg(
                format(
                    '%s:%s:%s:%s:%s:grantable=%s',
                    owner_name,
                    schema_name,
                    object_type,
                    grantee_name,
                    privilege_type,
                    is_grantable
                ),
                ', ' ORDER BY owner_name, schema_name, object_type,
                grantee_name, privilege_type, is_grantable
            )
            FROM unexpected
        )
    INTO missing_tables, unexpected_tables;

    IF missing_tables IS NOT NULL OR unexpected_tables IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B managed storage default-ACL signature drift; missing=[%s]; unexpected=[%s]',
                COALESCE(missing_tables, 'none'),
                COALESCE(unexpected_tables, 'none')
            );
    END IF;

    -- Only these postgres-owned role scopes are reviewed: application-owned
    -- public table/sequence/function defaults, the exact storage signature
    -- above, and global function defaults. anon/authenticated are client roles;
    -- service_role is a managed elevated server role. This catches global
    -- table/sequence grants and every additional non-public schema instead of
    -- excluding all of storage by name.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_default_acl AS defaults
        JOIN pg_catalog.pg_roles AS owner_role
            ON owner_role.oid = defaults.defaclrole
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = defaults.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
            ON grantee_role.oid = acl.grantee
        WHERE owner_role.rolname = 'postgres'
          AND (
              acl.grantee = 0
              OR grantee_role.rolname IN (
                  'anon',
                  'authenticated',
                  'service_role'
              )
          )
          AND NOT (
              (
                  namespace.nspname IN ('public', 'storage')
                  AND defaults.defaclobjtype IN (
                      'r'::pg_catalog."char",
                      'S'::pg_catalog."char",
                      'f'::pg_catalog."char"
                  )
              )
              OR (
                  defaults.defaclnamespace = 0
                  AND defaults.defaclobjtype = 'f'::pg_catalog."char"
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B unreviewed postgres role default-ACL scope detected';
    END IF;

    -- Prove the reviewed storage schema-local function grants are effective
    -- for both client roles and the managed elevated server role when combined
    -- with the current global/hard-wired function defaults.
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            (anon_role_oid),
            (authenticated_role_oid),
            (service_role_oid)
        ) AS managed_storage_role(role_oid)
        JOIN pg_catalog.pg_roles AS owner_role
            ON owner_role.rolname = 'postgres'
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.nspname = 'storage'
        LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
            ON global_defaults.defaclrole = owner_role.oid
           AND global_defaults.defaclobjtype = 'f'::pg_catalog."char"
           AND global_defaults.defaclnamespace = 0
        LEFT JOIN pg_catalog.pg_default_acl AS storage_defaults
            ON storage_defaults.defaclrole = owner_role.oid
           AND storage_defaults.defaclobjtype = 'f'::pg_catalog."char"
           AND storage_defaults.defaclnamespace = namespace.oid
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    global_defaults.defaclacl,
                    pg_catalog.acldefault(
                        'f'::pg_catalog."char",
                        owner_role.oid
                    )
                ) || COALESCE(
                    storage_defaults.defaclacl,
                    ARRAY[]::aclitem[]
                )
            ) AS acl
            WHERE acl.grantee = managed_storage_role.role_oid
              AND acl.privilege_type = 'EXECUTE'
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B managed storage function default EXECUTE is not effective';
    END IF;

    -- Public is application-controlled. A global function row was absent in
    -- the reviewed input, which is valid because PostgreSQL's hard-wired
    -- default supplies PUBLIC EXECUTE until the migration revokes it.

    FOR default_expectation IN
        SELECT *
        FROM (VALUES
            ('r'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('r'::pg_catalog."char", 'public'::name, 'authenticated'::name),
            ('S'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('S'::pg_catalog."char", 'public'::name, 'authenticated'::name),
            ('f'::pg_catalog."char", 'public'::name, 'anon'::name),
            ('f'::pg_catalog."char", 'public'::name, 'authenticated'::name)
        ) AS expected(object_type, schema_name, grantee_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_default_acl AS defaults
            JOIN pg_catalog.pg_roles AS owner_role
                ON owner_role.oid = defaults.defaclrole
            LEFT JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = defaults.defaclnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
            WHERE owner_role.rolname = 'postgres'
              AND defaults.defaclobjtype = default_expectation.object_type
              AND namespace.nspname IS NOT DISTINCT FROM
                  default_expectation.schema_name
              AND COALESCE(grantee.rolname, 'PUBLIC') =
                  default_expectation.grantee_name
              AND (
                  default_expectation.object_type <> 'f'::pg_catalog."char"
                  OR acl.privilege_type = 'EXECUTE'
              )
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B expected postgres default ACL absent: type=%s scope=%s grantee=%s',
                    default_expectation.object_type,
                    COALESCE(default_expectation.schema_name, '<all_schemas>'),
                    default_expectation.grantee_name
                );
        END IF;
    END LOOP;

    SELECT role_row.rolsuper
    INTO current_role_is_superuser
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = current_user;

    can_manage_defaults := COALESCE(current_role_is_superuser, false)
        OR pg_catalog.pg_has_role(current_user, 'postgres', 'MEMBER');

    IF NOT COALESCE(can_manage_defaults, false) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B executor cannot perform postgres-owned core operations';
    END IF;
END
$phase32b_preflight$;

ROLLBACK;
