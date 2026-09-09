/*
Phase 3.2B: transactional Supabase security hardening.

REVIEW-ONLY PACKAGE: this repository does not contain the exact names of all 34
audited public base tables or the deployed definitions of the three security-
definer helpers. The explicit stop below makes this migration fail before any
change until the table list is copied from Audit Section 01 and reviewed.

No helper function is replaced by this migration. Run
phase-3.2b-helper-function-definitions.sql and prepare a separately reviewed
follow-up migration from the exact deployed definitions.
*/

BEGIN;

-- Preflight: required roles, relations, columns, RLS, view support, and the one
-- authenticated marketplace-party INSERT policy must match the audited shape.
DO $phase32b_preflight$
DECLARE
    required_role text;
    required_table text;
    required_column text;
    insert_policy_count integer;
    current_role_is_superuser boolean;
    can_manage_defaults boolean;
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B requires PostgreSQL 15 or newer';
    END IF;

    FOREACH required_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role',
        'postgres',
        'supabase_admin'
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

    FOREACH required_table IN ARRAY ARRAY[
        'category',
        'marketplace_party',
        'product',
        'product_3d_model',
        'product_color',
        'product_enrichment_assignment',
        'product_image'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = required_table
              AND relation.relkind IN ('r', 'p')
              AND relation.relrowsecurity
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = format(
                    'Phase 3.2B expected an RLS-enabled table: public.%s',
                    required_table
                );
        END IF;
    END LOOP;

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
      AND policy.polcmd = 'a'
      AND (
          0 = ANY(policy.polroles)
          OR (
              SELECT role_row.oid
              FROM pg_catalog.pg_roles AS role_row
              WHERE role_row.rolname = 'authenticated'
          ) = ANY(policy.polroles)
      );

    IF insert_policy_count <> 1 THEN
        RAISE EXCEPTION USING
            MESSAGE = format(
                'Phase 3.2B expected one authenticated marketplace_party INSERT policy; found %s',
                insert_policy_count
            );
    END IF;

    SELECT role_row.rolsuper
    INTO current_role_is_superuser
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = current_user;

    can_manage_defaults := COALESCE(current_role_is_superuser, false)
        OR (
            pg_catalog.pg_has_role(
                current_user,
                'postgres',
                'MEMBER'
            )
            AND pg_catalog.pg_has_role(
                current_user,
                'supabase_admin',
                'MEMBER'
            )
        );

    IF NOT COALESCE(can_manage_defaults, false) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2B executor cannot alter postgres and supabase_admin default privileges';
    END IF;
END
$phase32b_preflight$;

/*
DEPLOYMENT BLOCKER: replace this entire DO block with explicit, reviewed REVOKE
statements. The first two ON TABLE lists must contain every one of the 34 names
from Audit Section 01. A third statement must explicitly list tables whose anon
SELECT policy is not an intentional public API surface. Review Audit Sections
02 and 03 together for that classification. Do not use ON ALL TABLES IN SCHEMA.

Required statement shapes:

  REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN
  ON TABLE public.<each reviewed base table, explicitly listed>
  FROM anon;

  REVOKE TRUNCATE, REFERENCES, TRIGGER, MAINTAIN
  ON TABLE public.<the same explicit reviewed base-table list>
  FROM authenticated;

  REVOKE SELECT
  ON TABLE public.<each reviewed non-public base table, explicitly listed>
  FROM anon;
*/
DO $phase32b_reviewed_table_list_required$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'Phase 3.2B blocked: add the reviewed 34-table and anon-SELECT lists';
END
$phase32b_reviewed_table_list_required$;

-- Seller approval: column privileges and RLS independently prevent clients
-- from choosing generated IDs or moderation state.
REVOKE INSERT, UPDATE, DELETE ON TABLE public.marketplace_party
FROM PUBLIC, anon;

REVOKE INSERT ON TABLE public.marketplace_party FROM authenticated;
REVOKE INSERT (id, approval_state, state_reason)
ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

GRANT INSERT (
    user_id,
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
CREATE POLICY phase32b_product_color_read_guard
ON public.product_color
AS RESTRICTIVE
FOR SELECT
TO anon, authenticated
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
CREATE POLICY phase32b_product_image_read_guard
ON public.product_image
AS RESTRICTIVE
FOR SELECT
TO anon, authenticated
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
CREATE POLICY phase32b_product_3d_model_read_guard
ON public.product_3d_model
AS RESTRICTIVE
FOR SELECT
TO anon, authenticated
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

-- Child writes remain granted by the existing operation-specific or FOR ALL
-- policies, but every applicable seller write must also pass these restrictive
-- ownership-and-approval guards. Administrators remain allowed.
DROP POLICY IF EXISTS phase32b_product_color_insert_guard ON public.product_color;
CREATE POLICY phase32b_product_color_insert_guard
ON public.product_color AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_color.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_color_update_guard ON public.product_color;
CREATE POLICY phase32b_product_color_update_guard
ON public.product_color AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_color.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
)
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_color.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_color_delete_guard ON public.product_color;
CREATE POLICY phase32b_product_color_delete_guard
ON public.product_color AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_color.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_image_insert_guard ON public.product_image;
CREATE POLICY phase32b_product_image_insert_guard
ON public.product_image AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_image.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_image_update_guard ON public.product_image;
CREATE POLICY phase32b_product_image_update_guard
ON public.product_image AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_image.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
)
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_image.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_image_delete_guard ON public.product_image;
CREATE POLICY phase32b_product_image_delete_guard
ON public.product_image AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_image.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_insert_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_insert_guard
ON public.product_3d_model AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_3d_model.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_update_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_update_guard
ON public.product_3d_model AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_3d_model.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
)
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_3d_model.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_product_3d_model_delete_guard
ON public.product_3d_model;
CREATE POLICY phase32b_product_3d_model_delete_guard
ON public.product_3d_model AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_3d_model.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_insert_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_insert_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_enrichment_assignment.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_update_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_update_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR UPDATE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_enrichment_assignment.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
)
WITH CHECK (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_enrichment_assignment.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

DROP POLICY IF EXISTS phase32b_enrichment_delete_guard
ON public.product_enrichment_assignment;
CREATE POLICY phase32b_enrichment_delete_guard
ON public.product_enrichment_assignment AS RESTRICTIVE FOR DELETE TO authenticated
USING (
    public.is_admin()
    OR (
        public.current_party_is_approved()
        AND EXISTS (
            SELECT 1 FROM public.product AS parent_product
            WHERE parent_product.id = product_enrichment_assignment.product_id
              AND parent_product.marketplace_party_id =
                  public.current_marketplace_party_id()
        )
    )
);

-- Future objects receive no implicit client access. Required grants must be
-- made explicitly by the migration that creates each object.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

COMMIT;
