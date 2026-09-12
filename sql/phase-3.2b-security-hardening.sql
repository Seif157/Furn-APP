/*
Phase 3.2B: transactional Supabase security hardening.

REVIEW-ONLY PACKAGE: the exact 34-table inventory, anonymous-read classification,
and deployed definitions of the three security-definer helpers are incorporated
below. The migration remains fail-closed on schema, policy, signature, role, or
deployment-authority drift. It has not been executed against Supabase.
*/

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

    -- Exact Phase 3.2A mixed read policies. The full predicate is compared after
    -- deterministic whitespace removal, so a broadened expression such as
    -- "OR true" cannot pass merely by retaining expected keywords.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
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
                    SELECT 1
                    FROM public.product AS parent_product
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
                    SELECT 1
                    FROM public.product AS parent_product
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
                    SELECT 1
                    FROM public.product AS parent_product
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
                    SELECT 1
                    FROM public.product AS parent_product
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
        ) AS expected(table_name, policy_name, expected_using_expression)
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
           OR pg_catalog.regexp_replace(
               lower(actual_policy.using_expr),
               '[[:space:]]',
               '',
               'g'
           ) IS DISTINCT FROM pg_catalog.regexp_replace(
               lower(policy_expectation.expected_using_expression),
               '[[:space:]]',
               '',
               'g'
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

    -- The audit found table, sequence, and function entries only in public.
    -- A global function row was absent, which is valid: PostgreSQL's hard-wired
    -- default still gives PUBLIC EXECUTE and is revoked by a separate command.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_default_acl AS defaults
        JOIN pg_catalog.pg_roles AS owner_role
            ON owner_role.oid = defaults.defaclrole
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = defaults.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE owner_role.rolname = 'postgres'
          AND COALESCE(grantee.rolname, 'PUBLIC')
              IN ('PUBLIC', 'anon', 'authenticated')
          AND (
              defaults.defaclobjtype IN (
                  'r'::pg_catalog."char",
                  'S'::pg_catalog."char",
                  'f'::pg_catalog."char"
              )
              AND namespace.nspname IS DISTINCT FROM 'public'
              AND NOT (
                  defaults.defaclobjtype = 'f'::pg_catalog."char"
                  AND defaults.defaclnamespace = 0
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postgres default-ACL namespace scope drift detected';
    END IF;

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

-- Existing public base-table grants use the exact reviewed 34-table inventory.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
ON TABLE
    public.address,
    public.admin_user,
    public.cart,
    public.cart_line,
    public.category,
    public.commission,
    public.commission_reversal,
    public.custom_offering,
    public.customer_profile,
    public.design,
    public.design_product_reference,
    public.design_version,
    public.furnishing_request,
    public.furnishing_request_design_version,
    public.marketplace_party,
    public.offer,
    public.offer_line_item,
    public.order_line_item,
    public.party_capability,
    public.payment,
    public.platform_config,
    public.product,
    public.product_3d_model,
    public.product_color,
    public.product_enrichment_assignment,
    public.product_enrichment_attribute,
    public.product_image,
    public.purchase_order,
    public.refund,
    public.review,
    public.saved_space,
    public.service_request,
    public.service_type,
    public.settlement
FROM PUBLIC, anon;

REVOKE TRUNCATE, REFERENCES, TRIGGER
ON TABLE
    public.address,
    public.admin_user,
    public.cart,
    public.cart_line,
    public.category,
    public.commission,
    public.commission_reversal,
    public.custom_offering,
    public.customer_profile,
    public.design,
    public.design_product_reference,
    public.design_version,
    public.furnishing_request,
    public.furnishing_request_design_version,
    public.marketplace_party,
    public.offer,
    public.offer_line_item,
    public.order_line_item,
    public.party_capability,
    public.payment,
    public.platform_config,
    public.product,
    public.product_3d_model,
    public.product_color,
    public.product_enrichment_assignment,
    public.product_enrichment_attribute,
    public.product_image,
    public.purchase_order,
    public.refund,
    public.review,
    public.saved_space,
    public.service_request,
    public.service_type,
    public.settlement
FROM authenticated;

-- Anonymous SELECT is deterministic: first remove PUBLIC/anon SELECT from the
-- reviewed inventory, then regrant only the exact 12-table allowlist.
REVOKE SELECT
ON TABLE
    public.category,
    public.custom_offering,
    public.marketplace_party,
    public.party_capability,
    public.product,
    public.product_3d_model,
    public.product_color,
    public.product_enrichment_assignment,
    public.product_enrichment_attribute,
    public.product_image,
    public.review,
    public.service_type
FROM PUBLIC, anon;

REVOKE SELECT
ON TABLE
    public.address,
    public.admin_user,
    public.cart,
    public.cart_line,
    public.commission,
    public.commission_reversal,
    public.customer_profile,
    public.design,
    public.design_product_reference,
    public.design_version,
    public.furnishing_request,
    public.furnishing_request_design_version,
    public.offer,
    public.offer_line_item,
    public.order_line_item,
    public.payment,
    public.platform_config,
    public.purchase_order,
    public.refund,
    public.saved_space,
    public.service_request,
    public.settlement
FROM PUBLIC, anon;

GRANT SELECT
ON TABLE
    public.category,
    public.custom_offering,
    public.marketplace_party,
    public.party_capability,
    public.product,
    public.product_3d_model,
    public.product_color,
    public.product_enrichment_assignment,
    public.product_enrichment_attribute,
    public.product_image,
    public.review,
    public.service_type
TO anon;

-- MAINTAIN was added in PostgreSQL 17. Dynamic parsing keeps this transaction
-- valid on PostgreSQL 15/16, where the privilege does not exist.
DO $phase32b_revoke_maintain$
BEGIN
    IF current_setting('server_version_num')::integer >= 170000 THEN
        EXECUTE 'REVOKE MAINTAIN ON TABLE '
            || 'public.address, public.admin_user, public.cart, public.cart_line, '
            || 'public.category, public.commission, public.commission_reversal, '
            || 'public.custom_offering, public.customer_profile, public.design, '
            || 'public.design_product_reference, public.design_version, '
            || 'public.furnishing_request, '
            || 'public.furnishing_request_design_version, '
            || 'public.marketplace_party, public.offer, public.offer_line_item, '
            || 'public.order_line_item, public.party_capability, public.payment, '
            || 'public.platform_config, public.product, public.product_3d_model, '
            || 'public.product_color, public.product_enrichment_assignment, '
            || 'public.product_enrichment_attribute, public.product_image, '
            || 'public.purchase_order, public.refund, public.review, '
            || 'public.saved_space, public.service_request, public.service_type, '
            || 'public.settlement FROM PUBLIC, anon, authenticated';
    END IF;
END
$phase32b_revoke_maintain$;

-- Seller approval: normalize table and every audited column privilege before
-- regranting the exact client-write surface. RLS independently enforces values.
REVOKE INSERT, UPDATE, DELETE ON TABLE public.marketplace_party
FROM PUBLIC, anon;

REVOKE INSERT, UPDATE ON TABLE public.marketplace_party FROM authenticated;

REVOKE INSERT (
    id,
    user_id,
    business_name,
    business_description,
    logo_url,
    coverage_area,
    approval_state,
    state_reason
)
ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

REVOKE UPDATE (
    id,
    user_id,
    business_name,
    business_description,
    logo_url,
    coverage_area,
    approval_state,
    state_reason
)
ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

GRANT INSERT (
    user_id,
    business_name,
    business_description,
    logo_url,
    coverage_area
) ON TABLE public.marketplace_party TO authenticated;

GRANT UPDATE (
    business_name,
    business_description,
    logo_url,
    coverage_area
) ON TABLE public.marketplace_party TO authenticated;

DO $phase32b_marketplace_insert_policy$
DECLARE
    insert_policy_name name;
BEGIN
    SELECT policy.polname
    INTO STRICT insert_policy_name
    FROM pg_catalog.pg_policy AS policy
    WHERE policy.polrelid = 'public.marketplace_party'::regclass
      AND policy.polcmd = 'a'::pg_catalog."char"
      AND (
          0 = ANY(policy.polroles)
          OR (
              SELECT role_row.oid
              FROM pg_catalog.pg_roles AS role_row
              WHERE role_row.rolname = 'authenticated'
          ) = ANY(policy.polroles)
      );

    EXECUTE format(
        'ALTER POLICY %I ON public.marketplace_party WITH CHECK ('
        || 'user_id = auth.uid() '
        || 'AND approval_state = ''pending''::public.party_approval_state '
        || 'AND state_reason IS NULL)',
        insert_policy_name
    );
END
$phase32b_marketplace_insert_policy$;

-- The financial view must use the caller's grants and underlying RLS.
REVOKE SELECT ON TABLE public.order_financial_position FROM PUBLIC, anon;
GRANT SELECT ON TABLE public.order_financial_position TO authenticated, service_role;
ALTER VIEW public.order_financial_position SET (security_invoker = true);

-- Split only the six explicitly reviewed mixed policies. Each ALTER installs
-- the complete audited predicate explicitly; no catalog text is reused at
-- runtime and role-only alteration cannot preserve unnoticed predicate drift.
ALTER POLICY custom_offering_select_published_or_own
ON public.custom_offering
TO authenticated
USING (
    publication_state = 'published'::public.custom_offering_state
    OR marketplace_party_id = public.current_marketplace_party_id()
    OR public.is_admin()
);

ALTER POLICY product_select_published_or_own
ON public.product
TO authenticated
USING (
    lifecycle_state = 'published'::public.product_lifecycle_state
    OR marketplace_party_id = public.current_marketplace_party_id()
    OR public.is_admin()
);

ALTER POLICY product_color_select
ON public.product_color
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND (
              parent_product.lifecycle_state =
                  'published'::public.product_lifecycle_state
              OR parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

ALTER POLICY product_image_select
ON public.product_image
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND (
              parent_product.lifecycle_state =
                  'published'::public.product_lifecycle_state
              OR parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

ALTER POLICY product_3d_model_select
ON public.product_3d_model
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND (
              parent_product.lifecycle_state =
                  'published'::public.product_lifecycle_state
              OR parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

ALTER POLICY product_enrichment_assignment_select
ON public.product_enrichment_assignment
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND (
              parent_product.lifecycle_state =
                  'published'::public.product_lifecycle_state
              OR parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

CREATE POLICY phase32b_custom_offering_anon_read
ON public.custom_offering
FOR SELECT
TO anon
USING (
    publication_state = 'published'::public.custom_offering_state
);

CREATE POLICY phase32b_custom_offering_anon_read_guard
ON public.custom_offering
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    publication_state = 'published'::public.custom_offering_state
);

-- Category reads: inactive categories are never client-public; authenticated
-- administrators remain exempt through the existing, audited helper.
DROP POLICY IF EXISTS phase32b_category_anon_read_guard ON public.category;
CREATE POLICY phase32b_category_anon_read_guard
ON public.category
AS RESTRICTIVE
FOR SELECT
TO anon
USING (is_active = true);

DROP POLICY IF EXISTS phase32b_category_authenticated_read_guard ON public.category;
CREATE POLICY phase32b_category_authenticated_read_guard
ON public.category
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (is_active = true OR public.is_admin());

-- Product reads: the product predicate only consults its two parent tables.
-- It never queries product children, preventing product/child policy recursion.
DROP POLICY IF EXISTS phase32b_product_owner_read ON public.product;
CREATE POLICY phase32b_product_owner_read
ON public.product
FOR SELECT
TO authenticated
USING (
    marketplace_party_id = public.current_marketplace_party_id()
    OR public.is_admin()
);

DROP POLICY IF EXISTS phase32b_product_anon_read ON public.product;
CREATE POLICY phase32b_product_anon_read
ON public.product
FOR SELECT
TO anon
USING (
    lifecycle_state = 'published'
    AND EXISTS (
        SELECT 1
        FROM public.marketplace_party AS seller
        WHERE seller.id = product.marketplace_party_id
          AND seller.approval_state = 'approved'
    )
    AND EXISTS (
        SELECT 1
        FROM public.category AS product_category
        WHERE product_category.id = product.category_id
          AND product_category.is_active = true
    )
);

DROP POLICY IF EXISTS phase32b_product_anon_read_guard ON public.product;
CREATE POLICY phase32b_product_anon_read_guard
ON public.product
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    lifecycle_state = 'published'
    AND EXISTS (
        SELECT 1
        FROM public.marketplace_party AS seller
        WHERE seller.id = product.marketplace_party_id
          AND seller.approval_state = 'approved'
    )
    AND EXISTS (
        SELECT 1
        FROM public.category AS product_category
        WHERE product_category.id = product.category_id
          AND product_category.is_active = true
    )
);

DROP POLICY IF EXISTS phase32b_product_authenticated_read_guard ON public.product;
CREATE POLICY phase32b_product_authenticated_read_guard
ON public.product
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    (
        lifecycle_state = 'published'
        AND EXISTS (
            SELECT 1
            FROM public.marketplace_party AS seller
            WHERE seller.id = product.marketplace_party_id
              AND seller.approval_state = 'approved'
        )
        AND EXISTS (
            SELECT 1
            FROM public.category AS product_category
            WHERE product_category.id = product.category_id
              AND product_category.is_active = true
        )
    )
    OR marketplace_party_id = public.current_marketplace_party_id()
    OR public.is_admin()
);

-- Child reads follow the parent product's public/owner/admin visibility. The
-- explicit owner policies preserve access to child rows of seller drafts.
DROP POLICY IF EXISTS phase32b_product_color_owner_read ON public.product_color;
CREATE POLICY phase32b_product_color_owner_read
ON public.product_color
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND (
              parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

DROP POLICY IF EXISTS phase32b_product_color_read_guard ON public.product_color;
DROP POLICY IF EXISTS phase32b_product_color_anon_read ON public.product_color;
CREATE POLICY phase32b_product_color_anon_read
ON public.product_color
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_color.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_color_anon_read_guard
ON public.product_color;
CREATE POLICY phase32b_product_color_anon_read_guard
ON public.product_color
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_color.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_color_authenticated_read_guard
ON public.product_color;
CREATE POLICY phase32b_product_color_authenticated_read_guard
ON public.product_color
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_color.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_image_owner_read ON public.product_image;
CREATE POLICY phase32b_product_image_owner_read
ON public.product_image
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND (
              parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

DROP POLICY IF EXISTS phase32b_product_image_read_guard ON public.product_image;
DROP POLICY IF EXISTS phase32b_product_image_anon_read ON public.product_image;
CREATE POLICY phase32b_product_image_anon_read
ON public.product_image
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_image.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_image_anon_read_guard
ON public.product_image;
CREATE POLICY phase32b_product_image_anon_read_guard
ON public.product_image
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_image.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_image_authenticated_read_guard
ON public.product_image;
CREATE POLICY phase32b_product_image_authenticated_read_guard
ON public.product_image
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_image.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_owner_read ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_owner_read
ON public.product_3d_model
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND (
              parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_read_guard
ON public.product_3d_model;
DROP POLICY IF EXISTS phase32b_product_3d_model_anon_read
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_anon_read
ON public.product_3d_model
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_3d_model.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_anon_read_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_anon_read_guard
ON public.product_3d_model
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_3d_model.product_id
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_authenticated_read_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_authenticated_read_guard
ON public.product_3d_model
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_3d_model.product_id
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_owner_read
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_owner_read
ON public.product_enrichment_assignment
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND (
              parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
              OR public.is_admin()
          )
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_anon_read
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_anon_read
ON public.product_enrichment_assignment
FOR SELECT
TO anon
USING (
    confirmation_state = 'party_confirmed'
    AND EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_enrichment_assignment.product_id
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_anon_read_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_anon_read_guard
ON public.product_enrichment_assignment
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    confirmation_state = 'party_confirmed'
    AND EXISTS (
        SELECT 1
        FROM public.product AS visible_product
        WHERE visible_product.id = product_enrichment_assignment.product_id
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_authenticated_read_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_authenticated_read_guard
ON public.product_enrichment_assignment
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    (
        confirmation_state = 'party_confirmed'
        AND EXISTS (
            SELECT 1
            FROM public.product AS visible_product
            WHERE visible_product.id =
                product_enrichment_assignment.product_id
        )
    )
    OR EXISTS (
        SELECT 1
        FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
    OR public.is_admin()
);

-- Existing permissive seller policies continue to grant write paths. These
-- restrictive guards only constrain those paths to approved owning sellers;
-- they do not independently grant administrators or any other role access.
DROP POLICY IF EXISTS phase32b_product_color_insert_guard ON public.product_color;
CREATE POLICY phase32b_product_color_insert_guard
ON public.product_color AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_color_update_guard ON public.product_color;
CREATE POLICY phase32b_product_color_update_guard
ON public.product_color AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
)
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_color_delete_guard ON public.product_color;
CREATE POLICY phase32b_product_color_delete_guard
ON public.product_color AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_color.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_image_insert_guard ON public.product_image;
CREATE POLICY phase32b_product_image_insert_guard
ON public.product_image AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_image_update_guard ON public.product_image;
CREATE POLICY phase32b_product_image_update_guard
ON public.product_image AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
)
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_image_delete_guard ON public.product_image;
CREATE POLICY phase32b_product_image_delete_guard
ON public.product_image AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_image.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_insert_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_insert_guard
ON public.product_3d_model AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_update_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_update_guard
ON public.product_3d_model AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
)
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_delete_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_delete_guard
ON public.product_3d_model AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_3d_model.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_insert_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_insert_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_update_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_update_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
)
WITH CHECK (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_delete_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_delete_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.current_party_is_approved()
    AND EXISTS (
        SELECT 1 FROM public.product AS parent_product
        WHERE parent_product.id = product_enrichment_assignment.product_id
          AND parent_product.marketplace_party_id =
              public.current_marketplace_party_id()
    )
);

-- Fail before reducing function privileges if any policy still exposed to anon
-- references one of the restricted helpers. This checks every public policy,
-- including PUBLIC-targeted and mixed-role policies, without relying on Boolean
-- short-circuit behavior.
DO $phase32b_verify_anon_policy_dependencies$
DECLARE
    anon_role_oid oid;
BEGIN
    SELECT role_row.oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'anon';

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND (
              0 = ANY(policy.polroles)
              OR anon_role_oid = ANY(policy.polroles)
          )
          AND lower(concat_ws(
              ' ',
              pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
              pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true)
          )) ~ 'current_marketplace_party_id|current_party_is_approved|is_admin'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B anon-facing policy still depends on a restricted helper';
    END IF;
END
$phase32b_verify_anon_policy_dependencies$;

-- Preserve the exact zero-argument signatures, SQL/STABLE/definer behavior,
-- owner, and caller-bound semantics while eliminating search-path substitution.
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS pg_catalog.bool
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.admin_user AS admin_row
        WHERE admin_row.user_id = auth.uid()
          AND admin_row.is_active
    );
$function$;

CREATE OR REPLACE FUNCTION public.current_marketplace_party_id()
RETURNS pg_catalog.uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT party.id
    FROM public.marketplace_party AS party
    WHERE party.user_id = auth.uid();
$function$;

CREATE OR REPLACE FUNCTION public.current_party_is_approved()
RETURNS pg_catalog.bool
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.marketplace_party AS party
        WHERE party.user_id = auth.uid()
          AND party.approval_state =
              'approved'::public.party_approval_state
    );
$function$;

REVOKE EXECUTE ON FUNCTION public.is_admin() FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.current_marketplace_party_id()
FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.current_party_is_approved()
FROM PUBLIC, anon;

GRANT EXECUTE ON FUNCTION public.is_admin()
TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.current_marketplace_party_id()
TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.current_party_is_approved()
TO authenticated, service_role;

-- Future postgres-owned public tables/sequences become opt-in. Function EXECUTE
-- is global because PostgreSQL's implicit PUBLIC EXECUTE is a global default;
-- a schema-local revoke cannot subtract it. Preflight validates these scopes.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

-- Validate the resulting security state before commit. Any mismatch raises and
-- rolls the entire migration back; this is intentionally independent of the
-- external, read-only verification report.
DO $phase32b_postflight$
DECLARE
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
    anon_select_tables constant text[] := ARRAY[
        'category',
        'custom_offering',
        'marketplace_party',
        'party_capability',
        'product',
        'product_3d_model',
        'product_color',
        'product_enrichment_assignment',
        'product_enrichment_attribute',
        'product_image',
        'review',
        'service_type'
    ];
    policy_expectation record;
    policy_row record;
    helper_expectation record;
    helper_row record;
    expected_source text;
    actual_source text;
    missing_tables text;
    unexpected_tables text;
BEGIN
    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'anon';
    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'authenticated';
    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'service_role';
    SELECT oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles WHERE rolname = 'postgres';

    WITH expected(table_name) AS (
        SELECT unnest(expected_tables)
    ),
    actual(table_name) AS (
        SELECT relation.relname::text
        FROM pg_catalog.pg_class AS relation
        WHERE relation.relnamespace = 'public'::regnamespace
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

    IF missing_tables IS NOT NULL OR unexpected_tables IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           WHERE relation.relnamespace = 'public'::regnamespace
             AND relation.relkind IN ('r', 'p')
             AND NOT relation.relrowsecurity
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B postflight: 34-table inventory or RLS mismatch; missing=[%s]; unexpected=[%s]',
                COALESCE(missing_tables, 'none'),
                COALESCE(unexpected_tables, 'none')
            );
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
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relkind IN ('r', 'p')
          AND acl.grantee = 0
          AND acl.privilege_type IN (
              'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
              'REFERENCES', 'TRIGGER', 'MAINTAIN'
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relkind IN ('r', 'p')
          AND pg_catalog.has_table_privilege(
              anon_role_oid,
              relation.oid,
              'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: dangerous PUBLIC or anon privilege remains';
    END IF;

    IF current_setting('server_version_num')::integer >= 170000
       AND EXISTS (
           SELECT 1
           FROM pg_catalog.pg_class AS relation
           WHERE relation.relnamespace = 'public'::regnamespace
             AND relation.relkind IN ('r', 'p')
             AND (
                 pg_catalog.has_table_privilege(
                     anon_role_oid,
                     relation.oid,
                     'MAINTAIN'
                 )
                 OR pg_catalog.has_table_privilege(
                     authenticated_role_oid,
                     relation.oid,
                     'MAINTAIN'
                 )
             )
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: client MAINTAIN privilege remains';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(expected_tables) AS expected(table_name)
        WHERE pg_catalog.has_table_privilege(
            anon_role_oid,
            format('public.%I', expected.table_name),
            'SELECT'
        ) IS DISTINCT FROM (
            expected.table_name = ANY(anon_select_tables)
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: anonymous SELECT allowlist mismatch';
    END IF;

    IF pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.marketplace_party'::regclass,
        'INSERT'
    ) OR pg_catalog.has_table_privilege(
        authenticated_role_oid,
        'public.marketplace_party'::regclass,
        'UPDATE'
    ) OR pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.marketplace_party'::regclass,
        'INSERT, UPDATE, DELETE'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.marketplace_party'::regclass,
        'INSERT'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.marketplace_party'::regclass,
        'UPDATE'
    ) OR NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.marketplace_party'::regclass,
        'DELETE'
    ) OR EXISTS (
        SELECT 1
        FROM (VALUES
            ('id'::name, false, false),
            ('user_id'::name, true, false),
            ('business_name'::name, true, true),
            ('business_description'::name, true, true),
            ('logo_url'::name, true, true),
            ('coverage_area'::name, true, true),
            ('approval_state'::name, false, false),
            ('state_reason'::name, false, false)
        ) AS expected(column_name, can_insert, can_update)
        WHERE pg_catalog.has_column_privilege(
            authenticated_role_oid,
            'public.marketplace_party'::regclass,
            expected.column_name,
            'INSERT'
        ) IS DISTINCT FROM expected.can_insert
           OR pg_catalog.has_column_privilege(
               authenticated_role_oid,
               'public.marketplace_party'::regclass,
               expected.column_name,
               'UPDATE'
           ) IS DISTINCT FROM expected.can_update
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: marketplace_party grant matrix mismatch';
    END IF;

    SELECT
        policy.polroles,
        policy.polpermissive,
        pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true) AS using_expr,
        pg_catalog.pg_get_expr(
            policy.polwithcheck,
            policy.polrelid,
            true
        ) AS check_expr
    INTO STRICT policy_row
    FROM pg_catalog.pg_policy AS policy
    WHERE policy.polrelid = 'public.marketplace_party'::regclass
      AND policy.polcmd = 'a'::pg_catalog."char";

    IF NOT (
        policy_row.polroles @> ARRAY[authenticated_role_oid]::oid[]
        AND policy_row.polroles <@ ARRAY[authenticated_role_oid]::oid[]
    ) OR NOT policy_row.polpermissive
       OR policy_row.using_expr IS NOT NULL
       OR policy_row.check_expr IS NULL
       OR policy_row.check_expr !~* 'user_id.*auth\.uid'
       OR policy_row.check_expr !~* 'approval_state.*pending'
       OR policy_row.check_expr !~* 'state_reason.*is null'
       OR pg_catalog.regexp_replace(
           lower(policy_row.check_expr),
           '[[:space:]]',
           '',
           'g'
       ) ~ 'ortrue'
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: seller INSERT policy mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        WHERE relation.oid = 'public.order_financial_position'::regclass
          AND relation.relkind = 'v'
          AND relation.reloptions @> ARRAY['security_invoker=true']
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.aclexplode(
                  COALESCE(
                      relation.relacl,
                      pg_catalog.acldefault(
                          'r'::pg_catalog."char",
                          relation.relowner
                      )
                  )
              ) AS acl
              WHERE acl.grantee = 0
                AND acl.privilege_type = 'SELECT'
          )
          AND NOT pg_catalog.has_table_privilege(
              anon_role_oid,
              relation.oid,
              'SELECT'
          )
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
            MESSAGE = 'Phase 3.2B postflight: financial view hardening mismatch';
    END IF;

    -- The six retained mixed policies are compared against their complete,
    -- explicitly installed predicates. Whitespace is the only ignored syntax.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
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
        ) AS expected(table_name, policy_name, using_expression)
    LOOP
        SELECT
            policy.polroles,
            policy.polcmd,
            policy.polpermissive,
            pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true)
                AS using_expr,
            pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true)
                AS check_expr
        INTO STRICT policy_row
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relname = policy_expectation.table_name
          AND policy.polname = policy_expectation.policy_name;

        IF policy_row.polcmd <> 'r'::pg_catalog."char"
           OR NOT policy_row.polpermissive
           OR NOT (
               policy_row.polroles @> ARRAY[authenticated_role_oid]::oid[]
               AND policy_row.polroles <@ ARRAY[authenticated_role_oid]::oid[]
           )
           OR policy_row.check_expr IS NOT NULL
           OR pg_catalog.regexp_replace(
               lower(policy_row.using_expr),
               '[[:space:]]',
               '',
               'g'
           ) IS DISTINCT FROM pg_catalog.regexp_replace(
               lower(policy_expectation.using_expression),
               '[[:space:]]',
               '',
               'g'
           )
        THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B postflight: exact mixed-policy mismatch public.%s.%s',
                    policy_expectation.table_name,
                    policy_expectation.policy_name
                );
        END IF;
    END LOOP;

    -- Every expected Phase 3.2B read policy must exist with the reviewed role,
    -- command, mode, and a non-broadened predicate.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
            ('category'::name, 'phase32b_category_anon_read_guard'::name, anon_role_oid, false),
            ('category'::name, 'phase32b_category_authenticated_read_guard'::name, authenticated_role_oid, false),
            ('custom_offering'::name, 'phase32b_custom_offering_anon_read'::name, anon_role_oid, true),
            ('custom_offering'::name, 'phase32b_custom_offering_anon_read_guard'::name, anon_role_oid, false),
            ('product'::name, 'phase32b_product_owner_read'::name, authenticated_role_oid, true),
            ('product'::name, 'phase32b_product_anon_read'::name, anon_role_oid, true),
            ('product'::name, 'phase32b_product_anon_read_guard'::name, anon_role_oid, false),
            ('product'::name, 'phase32b_product_authenticated_read_guard'::name, authenticated_role_oid, false),
            ('product_color'::name, 'phase32b_product_color_owner_read'::name, authenticated_role_oid, true),
            ('product_color'::name, 'phase32b_product_color_anon_read'::name, anon_role_oid, true),
            ('product_color'::name, 'phase32b_product_color_anon_read_guard'::name, anon_role_oid, false),
            ('product_color'::name, 'phase32b_product_color_authenticated_read_guard'::name, authenticated_role_oid, false),
            ('product_image'::name, 'phase32b_product_image_owner_read'::name, authenticated_role_oid, true),
            ('product_image'::name, 'phase32b_product_image_anon_read'::name, anon_role_oid, true),
            ('product_image'::name, 'phase32b_product_image_anon_read_guard'::name, anon_role_oid, false),
            ('product_image'::name, 'phase32b_product_image_authenticated_read_guard'::name, authenticated_role_oid, false),
            ('product_3d_model'::name, 'phase32b_product_3d_model_owner_read'::name, authenticated_role_oid, true),
            ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read'::name, anon_role_oid, true),
            ('product_3d_model'::name, 'phase32b_product_3d_model_anon_read_guard'::name, anon_role_oid, false),
            ('product_3d_model'::name, 'phase32b_product_3d_model_authenticated_read_guard'::name, authenticated_role_oid, false),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_owner_read'::name, authenticated_role_oid, true),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read'::name, anon_role_oid, true),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_anon_read_guard'::name, anon_role_oid, false),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_authenticated_read_guard'::name, authenticated_role_oid, false)
        ) AS expected(table_name, policy_name, role_oid, is_permissive)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
            WHERE relation.relnamespace = 'public'::regnamespace
              AND relation.relname = policy_expectation.table_name
              AND policy.polname = policy_expectation.policy_name
              AND policy.polcmd = 'r'::pg_catalog."char"
              AND policy.polpermissive = policy_expectation.is_permissive
              AND policy.polroles = ARRAY[policy_expectation.role_oid]::oid[]
              AND policy.polqual IS NOT NULL
              AND pg_catalog.regexp_replace(
                  lower(pg_catalog.pg_get_expr(
                      policy.polqual,
                      policy.polrelid,
                      true
                  )),
                  '[[:space:]]',
                  '',
                  'g'
              ) !~ 'ortrue'
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B postflight: expected read policy mismatch public.%s.%s',
                    policy_expectation.table_name,
                    policy_expectation.policy_name
                );
        END IF;
    END LOOP;

    -- Exact guard count plus complete approved-owner ingredients and a separate
    -- permissive seller path for each guarded operation.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
            ('product_color'::name, 'phase32b_product_color_insert_guard'::name, 'a'::pg_catalog."char"),
            ('product_color'::name, 'phase32b_product_color_update_guard'::name, 'w'::pg_catalog."char"),
            ('product_color'::name, 'phase32b_product_color_delete_guard'::name, 'd'::pg_catalog."char"),
            ('product_image'::name, 'phase32b_product_image_insert_guard'::name, 'a'::pg_catalog."char"),
            ('product_image'::name, 'phase32b_product_image_update_guard'::name, 'w'::pg_catalog."char"),
            ('product_image'::name, 'phase32b_product_image_delete_guard'::name, 'd'::pg_catalog."char"),
            ('product_3d_model'::name, 'phase32b_product_3d_model_insert_guard'::name, 'a'::pg_catalog."char"),
            ('product_3d_model'::name, 'phase32b_product_3d_model_update_guard'::name, 'w'::pg_catalog."char"),
            ('product_3d_model'::name, 'phase32b_product_3d_model_delete_guard'::name, 'd'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_insert_guard'::name, 'a'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_update_guard'::name, 'w'::pg_catalog."char"),
            ('product_enrichment_assignment'::name, 'phase32b_enrichment_delete_guard'::name, 'd'::pg_catalog."char")
        ) AS expected(table_name, policy_name, policy_command)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS guard
            JOIN pg_catalog.pg_class AS relation ON relation.oid = guard.polrelid
            WHERE relation.relnamespace = 'public'::regnamespace
              AND relation.relname = policy_expectation.table_name
              AND guard.polname = policy_expectation.policy_name
              AND NOT guard.polpermissive
              AND guard.polcmd = policy_expectation.policy_command
              AND guard.polroles = ARRAY[authenticated_role_oid]::oid[]
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(guard.polqual, guard.polrelid, true),
                  pg_catalog.pg_get_expr(
                      guard.polwithcheck,
                      guard.polrelid,
                      true
                  )
              )) ~ 'current_party_is_approved'
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(guard.polqual, guard.polrelid, true),
                  pg_catalog.pg_get_expr(
                      guard.polwithcheck,
                      guard.polrelid,
                      true
                  )
              )) ~ 'current_marketplace_party_id'
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(guard.polqual, guard.polrelid, true),
                  pg_catalog.pg_get_expr(
                      guard.polwithcheck,
                      guard.polrelid,
                      true
                  )
              )) !~ 'is_admin|or[[:space:]]+true'
        ) OR NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS seller
            JOIN pg_catalog.pg_class AS relation ON relation.oid = seller.polrelid
            WHERE relation.relnamespace = 'public'::regnamespace
              AND relation.relname = policy_expectation.table_name
              AND seller.polname <> policy_expectation.policy_name
              AND seller.polpermissive
              AND seller.polcmd IN (
                  '*'::pg_catalog."char",
                  policy_expectation.policy_command
              )
              AND (
                  0 = ANY(seller.polroles)
                  OR authenticated_role_oid = ANY(seller.polroles)
              )
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(seller.polqual, seller.polrelid, true),
                  pg_catalog.pg_get_expr(
                      seller.polwithcheck,
                      seller.polrelid,
                      true
                  )
              )) ~ 'current_marketplace_party_id'
              AND lower(concat_ws(
                  ' ',
                  pg_catalog.pg_get_expr(seller.polqual, seller.polrelid, true),
                  pg_catalog.pg_get_expr(
                      seller.polwithcheck,
                      seller.polrelid,
                      true
                  )
              )) !~ 'or[[:space:]]+true'
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B postflight: child write path mismatch public.%s command=%s',
                    policy_expectation.table_name,
                    policy_expectation.policy_command
                );
        END IF;
    END LOOP;

    FOR helper_expectation IN
        SELECT *
        FROM (VALUES
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
        ) AS expected(function_name, return_type, source_text)
    LOOP
        SELECT
            function_row.*,
            language_row.lanname AS language_name
        INTO STRICT helper_row
        FROM pg_catalog.pg_proc AS function_row
        JOIN pg_catalog.pg_language AS language_row
            ON language_row.oid = function_row.prolang
        WHERE function_row.pronamespace = 'public'::regnamespace
          AND function_row.proname = helper_expectation.function_name
          AND function_row.pronargs = 0;

        expected_source := btrim(
            pg_catalog.regexp_replace(
                lower(helper_expectation.source_text),
                '[[:space:]]',
                '',
                'g'
            ),
            ';'
        );
        actual_source := btrim(
            pg_catalog.regexp_replace(
                lower(helper_row.prosrc),
                '[[:space:]]',
                '',
                'g'
            ),
            ';'
        );

        IF helper_row.prokind <> 'f'::pg_catalog."char"
           OR helper_row.provolatile <> 's'::pg_catalog."char"
           OR NOT helper_row.prosecdef
           OR helper_row.language_name <> 'sql'
           OR helper_row.prorettype <> helper_expectation.return_type
           OR pg_catalog.pg_get_userbyid(helper_row.proowner) <> 'postgres'
           OR pg_catalog.cardinality(helper_row.proconfig) <> 1
           OR NOT EXISTS (
               SELECT 1
               FROM unnest(helper_row.proconfig) AS setting
               WHERE pg_catalog.regexp_replace(
                   setting,
                   '^search_path=',
                   ''
               ) IN ('', '""')
           )
           OR actual_source IS DISTINCT FROM expected_source
           OR EXISTS (
               SELECT 1
               FROM pg_catalog.aclexplode(
                   COALESCE(
                       helper_row.proacl,
                       pg_catalog.acldefault(
                           'f'::pg_catalog."char",
                           helper_row.proowner
                       )
                   )
               ) AS acl
               WHERE acl.grantee = 0
                 AND acl.privilege_type = 'EXECUTE'
           )
           OR pg_catalog.has_function_privilege(
               anon_role_oid,
               helper_row.oid,
               'EXECUTE'
           )
           OR NOT pg_catalog.has_function_privilege(
               authenticated_role_oid,
               helper_row.oid,
               'EXECUTE'
           )
           OR NOT pg_catalog.has_function_privilege(
               service_role_oid,
               helper_row.oid,
               'EXECUTE'
           )
        THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B postflight: helper mismatch public.%s()',
                    helper_expectation.function_name
                );
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
        WHERE relation.relnamespace = 'public'::regnamespace
          AND (0 = ANY(policy.polroles) OR anon_role_oid = ANY(policy.polroles))
          AND lower(concat_ws(
              ' ',
              pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
              pg_catalog.pg_get_expr(
                  policy.polwithcheck,
                  policy.polrelid,
                  true
              )
          )) ~ 'current_marketplace_party_id|current_party_is_approved|is_admin'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: anon helper dependency remains';
    END IF;

    -- Compute effective defaults. A missing global row means acldefault(); a
    -- missing schema row contributes nothing. Public-schema defaults are added
    -- to global defaults, exactly as PostgreSQL applies them to future objects.
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('public_tables'::text, 'r'::pg_catalog."char", 'public'::name),
            ('public_sequences'::text, 'S'::pg_catalog."char", 'public'::name),
            ('public_functions'::text, 'f'::pg_catalog."char", 'public'::name),
            ('global_functions'::text, 'f'::pg_catalog."char", NULL::name)
        ) AS expected(scope_name, object_type, schema_name)
        LEFT JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.nspname = expected.schema_name
        LEFT JOIN pg_catalog.pg_default_acl AS global_defaults
            ON global_defaults.defaclrole = postgres_role_oid
           AND global_defaults.defaclobjtype = expected.object_type
           AND global_defaults.defaclnamespace = 0
        LEFT JOIN pg_catalog.pg_default_acl AS schema_defaults
            ON schema_defaults.defaclrole = postgres_role_oid
           AND schema_defaults.defaclobjtype = expected.object_type
           AND schema_defaults.defaclnamespace = namespace.oid
           AND expected.schema_name IS NOT NULL
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                global_defaults.defaclacl,
                pg_catalog.acldefault(
                    expected.object_type,
                    postgres_role_oid
                )
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
              expected.object_type IN (
                  'r'::pg_catalog."char",
                  'S'::pg_catalog."char"
              )
              OR acl.privilege_type = 'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postflight: unsafe effective postgres default privilege';
    END IF;
END
$phase32b_postflight$;

COMMIT;
