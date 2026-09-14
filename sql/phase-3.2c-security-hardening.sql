/*
Phase 3.2C targeted security hardening -- REVIEW ONLY.

This transaction is deliberately fail-closed on two unresolved review inputs:
the operation-level furnishing-request withdrawal decision and the item-by-item
mapping of the 19 FOR ALL policies / 122 audit findings. Do not remove either
gate without attaching the reviewed evidence described in the companion doc.
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
    helper_acl_grantees oid[];
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

    SELECT role_row.oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'anon';

    SELECT role_row.oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'authenticated';

    SELECT role_row.oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'service_role';

    SELECT role_row.oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'postgres';

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

    -- PUBLIC is a pseudo-role. Inspect its schema ACL as grantee OID zero;
    -- never attempt to resolve PUBLIC through pg_roles or to_regrole().
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

    IF NOT pg_catalog.has_schema_privilege(
        anon_role_oid,
        'public',
        'USAGE'
    ) OR pg_catalog.has_schema_privilege(
        anon_role_oid,
        'public',
        'CREATE'
    ) OR NOT pg_catalog.has_schema_privilege(
        authenticated_role_oid,
        'public',
        'USAGE'
    ) OR pg_catalog.has_schema_privilege(
        authenticated_role_oid,
        'public',
        'CREATE'
    ) OR NOT pg_catalog.has_schema_privilege(
        service_role_oid,
        'public',
        'USAGE'
    ) OR pg_catalog.has_schema_privilege(
        service_role_oid,
        'public',
        'CREATE'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C client/server schema privilege drift';
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

    IF pg_catalog.to_regprocedure(
        'public.current_customer_profile_id()'
    ) IS NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C missing customer-profile helper';
    END IF;

    SELECT function_metadata.oid
    INTO STRICT helper_oid
    FROM pg_catalog.pg_proc AS function_metadata
    WHERE function_metadata.oid =
        'public.current_customer_profile_id()'::pg_catalog.regprocedure
      AND function_metadata.pronargs = 0
      AND function_metadata.prorettype = 'pg_catalog.uuid'::pg_catalog.regtype
      AND function_metadata.prolang =
          (SELECT language.oid
           FROM pg_catalog.pg_language AS language
           WHERE language.lanname = 'sql')
      AND function_metadata.provolatile = 's'::pg_catalog."char"
      AND function_metadata.prosecdef
      AND function_metadata.proowner = postgres_role_oid
      AND function_metadata.proconfig =
          ARRAY['search_path=public, pg_temp']::text[]
      AND lower(function_metadata.prosrc) LIKE '%public.customer_profile%'
      AND lower(function_metadata.prosrc) LIKE '%auth.uid()%';

    IF NOT FOUND THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C customer-profile helper signature drift';
    END IF;

    SELECT array_agg(DISTINCT acl.grantee ORDER BY acl.grantee)
    INTO helper_acl_grantees
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
      AND acl.privilege_type = 'EXECUTE';

    IF NOT 0 = ANY(helper_acl_grantees)
       OR NOT pg_catalog.has_function_privilege(
           anon_role_oid,
           helper_oid,
           'EXECUTE'
       )
       OR NOT pg_catalog.has_function_privilege(
           authenticated_role_oid,
           helper_oid,
           'EXECUTE'
       )
       OR NOT pg_catalog.has_function_privilege(
           service_role_oid,
           helper_oid,
           'EXECUTE'
       )
       OR EXISTS (
           SELECT 1
           FROM unnest(helper_acl_grantees) AS grantee(role_oid)
           WHERE grantee.role_oid NOT IN (
               0,
               postgres_role_oid,
               anon_role_oid,
               authenticated_role_oid,
               service_role_oid
           )
       )
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C customer-profile helper grant drift';
    END IF;

    -- Revoking anonymous execution is safe only when neither an anon policy nor
    -- a PUBLIC policy (which also applies to anon) depends on this helper.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        JOIN pg_catalog.pg_depend AS dependency
            ON dependency.classid = 'pg_catalog.pg_policy'::pg_catalog.regclass
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

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('review'::pg_catalog.regclass, 'id'::name),
                ('review'::pg_catalog.regclass, 'customer_profile_id'::name),
                ('review'::pg_catalog.regclass, 'target_kind'::name),
                ('review'::pg_catalog.regclass, 'target_product_id'::name),
                ('review'::pg_catalog.regclass, 'target_marketplace_party_id'::name),
                ('review'::pg_catalog.regclass, 'target_service_request_id'::name),
                ('review'::pg_catalog.regclass, 'rating'::name),
                ('review'::pg_catalog.regclass, 'comment'::name),
                ('review'::pg_catalog.regclass, 'created_at'::name),
                ('service_type'::pg_catalog.regclass, 'id'::name),
                ('service_type'::pg_catalog.regclass, 'is_active'::name),
                ('party_capability'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('party_capability'::pg_catalog.regclass, 'service_type_id'::name),
                ('furnishing_request'::pg_catalog.regclass, 'customer_profile_id'::name),
                ('furnishing_request'::pg_catalog.regclass, 'lifecycle_state'::name)
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
        'marketplace_party',
        'service_request'
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
        FROM pg_catalog.pg_policy AS policy
        WHERE policy.polrelid =
              'public.furnishing_request'::pg_catalog.regclass
          AND policy.polname = 'furnishing_request_write_own'
          AND policy.polcmd = '*'::pg_catalog."char"
          AND policy.polpermissive
          AND policy.polroles = ARRAY[authenticated_role_oid]::oid[]
          AND policy.polqual IS NOT NULL
          AND policy.polwithcheck IS NOT NULL
          AND position(
              'customer_profile_id' IN lower(
                  pg_catalog.pg_get_expr(
                      policy.polqual,
                      policy.polrelid,
                      false
                  )
              )
          ) > 0
          AND position(
              'current_customer_profile_id' IN lower(
                  pg_catalog.pg_get_expr(
                      policy.polqual,
                      policy.polrelid,
                      false
                  )
              )
          ) > 0
          AND position(
              'customer_profile_id' IN lower(
                  pg_catalog.pg_get_expr(
                      policy.polwithcheck,
                      policy.polrelid,
                      false
                  )
              )
          ) > 0
          AND position(
              'current_customer_profile_id' IN lower(
                  pg_catalog.pg_get_expr(
                      policy.polwithcheck,
                      policy.polrelid,
                      false
                  )
              )
          ) > 0
          AND position(
              'is_admin' IN lower(
                  pg_catalog.concat_ws(
                      ' ',
                      pg_catalog.pg_get_expr(
                          policy.polqual,
                          policy.polrelid,
                          false
                      ),
                      pg_catalog.pg_get_expr(
                          policy.polwithcheck,
                          policy.polrelid,
                          false
                      )
                  )
              )
          ) = 0
          AND EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid =
                    'pg_catalog.pg_policy'::pg_catalog.regclass
                AND dependency.objid = policy.oid
                AND dependency.refclassid =
                    'pg_catalog.pg_proc'::pg_catalog.regclass
                AND dependency.refobjid = helper_oid
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policy AS policy
        WHERE policy.polname LIKE 'phase32c_%'
    ) OR pg_catalog.to_regclass('public.public_review') IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C policy/view baseline drift';
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

    IF (SELECT count(*) FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.cmd = 'ALL') <> 19 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C FOR ALL policy count drift';
    END IF;

    -- These settings are external, review-record gates. They are intentionally
    -- absent from this file, so this review-only transaction cannot be deployed
    -- until the missing evidence has been supplied and independently approved.
    IF current_setting(
        'furn_app.phase32c_disposition_evidence',
        true
    ) IS DISTINCT FROM 'reviewed_19_policies_and_122_findings' THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C disposition evidence gate is unresolved';
    END IF;

    IF current_setting(
        'furn_app.phase32c_withdrawal_decision',
        true
    ) IS DISTINCT FROM 'customer_direct_withdrawal_not_approved' THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C furnishing withdrawal workflow decision is unresolved';
    END IF;

    IF current_setting(
        'furn_app.phase32c_initial_state_decision',
        true
    ) IS DISTINCT FROM 'customer_insert_draft_only_approved' THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C furnishing initial-state decision is unresolved';
    END IF;
END
$phase32c_preflight$;

-- Harden the customer-profile identity helper without changing its UUID return
-- contract. All object references remain fully qualified with an empty path.
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

-- Raw review rows remain private to authenticated owners/admins. Anonymous
-- access is supplied only through the fixed, read-only public_review view.
REVOKE SELECT ON TABLE public.review FROM PUBLIC, anon;

CREATE POLICY phase32c_review_authenticated_read_guard
ON public.review
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    OR public.is_admin()
);

CREATE VIEW public.public_review
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    review_row.id,
    review_row.target_kind,
    review_row.target_product_id,
    review_row.target_marketplace_party_id,
    review_row.rating,
    review_row.comment,
    review_row.created_at
FROM public.review AS review_row
JOIN public.product AS reviewed_product
    ON reviewed_product.id = review_row.target_product_id
JOIN public.marketplace_party AS product_party
    ON product_party.id = reviewed_product.marketplace_party_id
JOIN public.category AS product_category
    ON product_category.id = reviewed_product.category_id
WHERE review_row.target_kind::text = 'product'
  AND review_row.target_product_id IS NOT NULL
  AND review_row.target_marketplace_party_id IS NULL
  AND review_row.target_service_request_id IS NULL
  AND reviewed_product.lifecycle_state = 'published'::public.product_state
  AND product_party.approval_state = 'approved'::public.party_approval_state
  AND product_category.is_active
  AND EXISTS (
      SELECT 1
      FROM public.product_color AS available_color
      WHERE available_color.product_id = reviewed_product.id
        AND available_color.stock_quantity > 0
  )
UNION ALL
SELECT
    review_row.id,
    review_row.target_kind,
    review_row.target_product_id,
    review_row.target_marketplace_party_id,
    review_row.rating,
    review_row.comment,
    review_row.created_at
FROM public.review AS review_row
JOIN public.marketplace_party AS reviewed_party
    ON reviewed_party.id = review_row.target_marketplace_party_id
WHERE review_row.target_kind::text = 'marketplace_party'
  AND review_row.target_product_id IS NULL
  AND review_row.target_marketplace_party_id IS NOT NULL
  AND review_row.target_service_request_id IS NULL
  AND reviewed_party.approval_state = 'approved'::public.party_approval_state;

ALTER VIEW public.public_review OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON TABLE public.public_review
FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT
ON TABLE public.public_review
TO anon, authenticated, service_role;

-- Restrictive guards constrain the already-existing permissive read paths, so
-- overlap cannot restore literal-true visibility.
CREATE POLICY phase32c_service_type_anon_read_guard
ON public.service_type
AS RESTRICTIVE
FOR SELECT
TO anon
USING (is_active);

CREATE POLICY phase32c_service_type_authenticated_read_guard
ON public.service_type
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    is_active
    OR public.is_admin()
);

CREATE POLICY phase32c_party_capability_anon_read_guard
ON public.party_capability
AS RESTRICTIVE
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.marketplace_party AS capability_party
        WHERE capability_party.id = party_capability.marketplace_party_id
          AND capability_party.approval_state =
              'approved'::public.party_approval_state
    )
    AND EXISTS (
        SELECT 1
        FROM public.service_type AS capability_service
        WHERE capability_service.id = party_capability.service_type_id
          AND capability_service.is_active
    )
);

CREATE POLICY phase32c_party_capability_authenticated_read_guard
ON public.party_capability
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    (
        EXISTS (
            SELECT 1
            FROM public.marketplace_party AS capability_party
            WHERE capability_party.id = party_capability.marketplace_party_id
              AND capability_party.approval_state =
                  'approved'::public.party_approval_state
        )
        AND EXISTS (
            SELECT 1
            FROM public.service_type AS capability_service
            WHERE capability_service.id = party_capability.service_type_id
              AND capability_service.is_active
        )
    )
    OR marketplace_party_id = public.current_marketplace_party_id()
    OR public.is_admin()
);

-- The review gate explicitly selects the conservative state model: direct
-- customer withdrawal is not approved. A distinct reviewed withdrawal workflow
-- must be added separately if the product requires one.
DROP POLICY furnishing_request_write_own ON public.furnishing_request;

CREATE POLICY phase32c_furnishing_request_insert_own
ON public.furnishing_request
FOR INSERT
TO authenticated
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state::text = 'draft'
);

CREATE POLICY phase32c_furnishing_request_update_own
ON public.furnishing_request
FOR UPDATE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state::text IN ('draft', 'open')
)
WITH CHECK (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state::text IN ('draft', 'open')
);

CREATE POLICY phase32c_furnishing_request_delete_own
ON public.furnishing_request
FOR DELETE
TO authenticated
USING (
    customer_profile_id = public.current_customer_profile_id()
    AND lifecycle_state::text IN ('draft', 'open')
);

-- Preserve the invoker-rights view definition and service access. Normalize
-- only client privileges; ALL is version-safe and includes MAINTAIN when the
-- server version supports it.
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
BEGIN
    SELECT role_row.oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'anon';

    SELECT role_row.oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'authenticated';

    SELECT role_row.oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'service_role';

    SELECT role_row.oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = 'postgres';

    helper_oid := 'public.current_customer_profile_id()'::pg_catalog.regprocedure;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_metadata
        WHERE function_metadata.oid = helper_oid
          AND (
              function_metadata.proowner <> postgres_role_oid
              OR function_metadata.provolatile <> 's'::pg_catalog."char"
              OR NOT function_metadata.prosecdef
              OR function_metadata.proconfig IS DISTINCT FROM
                  ARRAY['search_path=']::text[]
          )
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
    ) OR NOT pg_catalog.has_function_privilege(
        authenticated_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR NOT pg_catalog.has_function_privilege(
        service_role_oid,
        helper_oid,
        'EXECUTE'
    ) OR pg_catalog.has_function_privilege(
        anon_role_oid,
        helper_oid,
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight helper hardening mismatch';
    END IF;

    IF pg_catalog.has_table_privilege(
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
    ) OR NOT pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.public_review'::pg_catalog.regclass,
        'SELECT'
    ) OR EXISTS (
        SELECT 1
        FROM information_schema.columns AS column_metadata
        WHERE column_metadata.table_schema = 'public'
          AND column_metadata.table_name = 'public_review'
          AND column_metadata.column_name IN (
              'customer_profile_id',
              'target_service_request_id'
          )
    ) OR (SELECT count(*)
          FROM information_schema.columns AS column_metadata
          WHERE column_metadata.table_schema = 'public'
            AND column_metadata.table_name = 'public_review') <> 7
    THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight review exposure mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.views AS view_metadata
        WHERE view_metadata.table_schema = 'public'
          AND view_metadata.table_name = 'public_review'
          AND view_metadata.is_updatable <> 'NO'
    ) OR EXISTS (
        SELECT 1
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
          AND relation.relname = 'public_review'
          AND acl.grantee IN (
              0,
              anon_role_oid,
              authenticated_role_oid,
              service_role_oid
          )
          AND (
              acl.privilege_type <> 'SELECT'
              OR acl.is_grantable
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight public-review write exposure';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('review'::name, 'phase32c_review_authenticated_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
                ('service_type'::name, 'phase32c_service_type_anon_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
                ('service_type'::name, 'phase32c_service_type_authenticated_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_anon_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
                ('party_capability'::name, 'phase32c_party_capability_authenticated_read_guard'::name, 'SELECT'::text, 'RESTRICTIVE'::text),
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
          AND policy.tablename = 'furnishing_request'
          AND policy.policyname = 'furnishing_request_write_own'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight policy inventory mismatch';
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
            MESSAGE = 'Phase 3.2C postflight changed RLS/FORCE state';
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
    ) OR EXISTS (
        SELECT 1
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
          AND relation.relname = 'order_financial_position'
          AND acl.grantee IN (0, anon_role_oid, authenticated_role_oid)
          AND (
              acl.privilege_type <> 'SELECT'
              OR acl.is_grantable
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight financial-view privilege mismatch';
    END IF;

    IF NOT pg_catalog.has_table_privilege(
        service_role_oid,
        'public.public_review'::pg_catalog.regclass,
        'SELECT'
    ) OR NOT pg_catalog.has_function_privilege(
        service_role_oid,
        helper_oid,
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2C postflight service-role functionality mismatch';
    END IF;

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
            MESSAGE = 'Phase 3.2C postflight client elevation mismatch';
    END IF;
END
$phase32c_postflight$;

COMMIT;
