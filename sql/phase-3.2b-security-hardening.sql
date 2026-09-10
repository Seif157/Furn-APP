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
      AND policy.polcmd = 'a';

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
      AND policy.polcmd = 'a';

    IF insert_policy.polcmd <> 'a'
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
                pg_catalog.acldefault('r', relation.relowner)
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
                pg_catalog.acldefault('r', relation.relowner)
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

    -- Exact reviewed mixed read policies. Only these names are narrowed later;
    -- no catalog-driven predicate rewriting is permitted.
    FOR policy_expectation IN
        SELECT *
        FROM (VALUES
            (
                'custom_offering'::name,
                'custom_offering_select_published_or_own'::name,
                true
            ),
            ('product'::name, 'product_select_published_or_own'::name, false),
            ('product_color'::name, 'product_color_select'::name, false),
            ('product_image'::name, 'product_image_select'::name, false),
            ('product_3d_model'::name, 'product_3d_model_select'::name, false),
            (
                'product_enrichment_assignment'::name,
                'product_enrichment_assignment_select'::name,
                false
            )
        ) AS expected(table_name, policy_name, is_custom_offering)
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

        IF actual_policy.polcmd <> 'r'
           OR NOT actual_policy.polpermissive
           OR NOT (
               actual_policy.polroles @>
                   ARRAY[anon_role_oid, authenticated_role_oid]::oid[]
               AND actual_policy.polroles <@
                   ARRAY[anon_role_oid, authenticated_role_oid]::oid[]
           )
           OR actual_policy.check_expr IS NOT NULL
           OR actual_policy.using_expr IS NULL
           OR lower(actual_policy.using_expr) !~
               'current_marketplace_party_id|is_admin'
           OR (
               policy_expectation.is_custom_offering
               AND (
                   actual_policy.using_expr !~* 'publication_state.*published'
                   OR actual_policy.using_expr !~* 'current_marketplace_party_id'
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
            ('product_color'::name, 'a'::char),
            ('product_color'::name, 'w'::char),
            ('product_color'::name, 'd'::char),
            ('product_image'::name, 'a'::char),
            ('product_image'::name, 'w'::char),
            ('product_image'::name, 'd'::char),
            ('product_3d_model'::name, 'a'::char),
            ('product_3d_model'::name, 'w'::char),
            ('product_3d_model'::name, 'd'::char),
            ('product_enrichment_assignment'::name, 'a'::char),
            ('product_enrichment_assignment'::name, 'w'::char),
            ('product_enrichment_assignment'::name, 'd'::char)
        ) AS expected(table_name, policy_command)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policy AS policy
            JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
            WHERE relation.relnamespace = 'public'::regnamespace
              AND relation.relname = write_expectation.table_name
              AND policy.polpermissive
              AND policy.polcmd IN ('*', write_expectation.policy_command)
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

        SELECT lower(btrim(
            pg_catalog.regexp_replace(function_row.prosrc, '[[:space:]]+', ' ', 'g'),
            ' ;'
        ))
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

    -- Core migration handles only the confirmed postgres scopes: public-schema
    -- table/sequence ACLs and the global function ACL required to override
    -- PostgreSQL's implicit PUBLIC EXECUTE. Managed supabase_admin defaults are
    -- intentionally outside this transaction.
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
              (defaults.defaclobjtype IN ('r', 'S')
               AND namespace.nspname IS DISTINCT FROM 'public')
              OR (defaults.defaclobjtype = 'f' AND defaults.defaclnamespace <> 0)
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B postgres default-ACL namespace scope drift detected';
    END IF;

    FOR default_expectation IN
        SELECT *
        FROM (VALUES
            ('r'::char, 'public'::name, 'anon'::name),
            ('r'::char, 'public'::name, 'authenticated'::name),
            ('S'::char, 'public'::name, 'anon'::name),
            ('S'::char, 'public'::name, 'authenticated'::name),
            ('f'::char, NULL::name, 'PUBLIC'::name),
            ('f'::char, NULL::name, 'anon'::name),
            ('f'::char, NULL::name, 'authenticated'::name)
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
                  default_expectation.object_type <> 'f'
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
      AND policy.polcmd = 'a'
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
        || 'user_id = (SELECT auth.uid()) '
        || 'AND approval_state = ''pending'' '
        || 'AND state_reason IS NULL)',
        insert_policy_name
    );
END
$phase32b_marketplace_insert_policy$;

-- The financial view must use the caller's grants and underlying RLS.
REVOKE SELECT ON TABLE public.order_financial_position FROM PUBLIC, anon;
GRANT SELECT ON TABLE public.order_financial_position TO authenticated, service_role;
ALTER VIEW public.order_financial_position SET (security_invoker = true);

-- Split only the six explicitly reviewed mixed policies. Their metadata and the
-- custom-offering predicate were validated in preflight; no predicate is built
-- from catalog text at runtime.
ALTER POLICY custom_offering_select_published_or_own
ON public.custom_offering TO authenticated;

ALTER POLICY product_select_published_or_own
ON public.product TO authenticated;

ALTER POLICY product_color_select
ON public.product_color TO authenticated;

ALTER POLICY product_image_select
ON public.product_image TO authenticated;

ALTER POLICY product_3d_model_select
ON public.product_3d_model TO authenticated;

ALTER POLICY product_enrichment_assignment_select
ON public.product_enrichment_assignment TO authenticated;

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
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMIT;
