/*
A place for what the marketplace infers about a product, kept apart from what
a seller says about it.

Why a new table rather than product_enrichment_attribute. That table already
has an ai_proposed state, but Phase 3.2B deliberately hid unconfirmed rows from
customers with a restrictive policy, so search cannot read them. Writing
guesses as party_confirmed would present the platform's opinion as the seller's
word, and loosening 3.2B would reverse a reviewed security decision to buy a
ranking signal. Neither is acceptable, so inferences live here, where their
provenance is a column and not a convention.

What this table is for. No seller states a style, a room or a feel, so nothing
in the catalogue can answer "cosy", "hotel-like" or "for a small reception".
These tags let search rank such a sentence. They never filter: the API uses
them for soft scoring only, caps their contribution below a confirmed fact, and
labels every reason built from one as a guess.

Clients may read tags for published products and may never write them. Rows are
written by the owner, from a reviewed file, the same way the catalogue seed is.

Requires Phase 3.2D. One transaction; any failed check rolls everything back.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $search_tags_preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'furnishing_request_design_version'
          AND policy.policyname = 'phase32d_furnishing_request_design_version_delete_own'
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags require the applied Phase 3.2D migration';
    END IF;

    IF pg_catalog.to_regclass('public.product_search_tag') IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags are already applied';
    END IF;

    IF pg_catalog.to_regtype('public.product_state') IS NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags expect the product_state enum';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_enum AS enum_label
        WHERE enum_label.enumtypid = 'public.product_state'::pg_catalog.regtype
          AND enum_label.enumlabel = 'published'
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags expect a published product state';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('id'::name, 'uuid'::name),
                ('lifecycle_state'::name, 'product_state'::name)
        ) AS required(column_name, type_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute AS attribute
            JOIN pg_catalog.pg_type AS column_type
                ON column_type.oid = attribute.atttypid
            WHERE attribute.attrelid = 'public.product'::pg_catalog.regclass
              AND attribute.attname = required.column_name
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND column_type.typname = required.type_name
        )
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags column drift on public.product';
    END IF;
END
$search_tags_preflight$;

CREATE TABLE public.product_search_tag (
    product_id pg_catalog.uuid NOT NULL
        REFERENCES public.product (id) ON DELETE CASCADE,
    tag_kind pg_catalog.text NOT NULL,
    tag_slug pg_catalog.text NOT NULL,
    confidence pg_catalog.numeric(3, 2) NOT NULL,
    source pg_catalog.text NOT NULL DEFAULT 'ai_inferred',
    model_name pg_catalog.text NOT NULL,
    generated_at pg_catalog.timestamptz NOT NULL DEFAULT pg_catalog.now(),
    CONSTRAINT product_search_tag_pkey
        PRIMARY KEY (product_id, tag_kind, tag_slug),
    -- The kinds the API knows. A fourth kind would be invisible to it, so it
    -- is refused here rather than stored and silently ignored.
    CONSTRAINT product_search_tag_kind_known
        CHECK (tag_kind IN ('style', 'room_type', 'feel')),
    -- Slugs, not labels: the API matches these against its own vocabulary, in
    -- either language. Anything else cannot match and must not be stored.
    CONSTRAINT product_search_tag_slug_shape
        CHECK (tag_slug OPERATOR(pg_catalog.~) '^[a-z][a-z0-9_]{0,39}$'),
    CONSTRAINT product_search_tag_confidence_range
        CHECK (confidence OPERATOR(pg_catalog.>) 0 AND confidence OPERATOR(pg_catalog.<=) 1),
    -- Every row in this table is a guess. The column exists so that a future
    -- source has to be added deliberately, and so a reader never has to know
    -- the convention to learn the provenance.
    CONSTRAINT product_search_tag_source_known
        CHECK (source IN ('ai_inferred')),
    CONSTRAINT product_search_tag_model_named
        CHECK (pg_catalog.length(pg_catalog.btrim(model_name)) OPERATOR(pg_catalog.>) 0)
);

ALTER TABLE public.product_search_tag OWNER TO postgres;

COMMENT ON TABLE public.product_search_tag IS
'Platform-inferred style, room and feel tags. Not seller-stated facts: these '
'are generated by a model from the product''s own name, description and '
'photos, used only to rank fuzzy searches, and always shown to a customer as '
'a guess. Seller-stated attributes live in product_enrichment_attribute.';

COMMENT ON COLUMN public.product_search_tag.confidence IS
'How sure the generating model was, in (0, 1]. Ranking caps a guess below a '
'seller-confirmed attribute regardless of this value.';

ALTER TABLE public.product_search_tag ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.product_search_tag
FROM PUBLIC, anon, authenticated, service_role;

-- Read-only for every client, including the service role: rows are written by
-- the owner from a reviewed file, so no key the application holds can write a
-- guess into the catalogue's neighbourhood.
GRANT SELECT ON TABLE public.product_search_tag TO anon, authenticated;

CREATE POLICY product_search_tag_anon_read
ON public.product_search_tag
FOR SELECT
TO anon
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS tagged_product
        WHERE tagged_product.id = product_search_tag.product_id
          AND tagged_product.lifecycle_state = 'published'::public.product_state
    )
);

CREATE POLICY product_search_tag_authenticated_read
ON public.product_search_tag
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS tagged_product
        WHERE tagged_product.id = product_search_tag.product_id
          AND tagged_product.lifecycle_state = 'published'::public.product_state
    )
);

-- Defence in depth, in the shape Phase 3.2B established: a permissive policy
-- added later cannot widen this beyond published products.
CREATE POLICY product_search_tag_published_only_guard
ON public.product_search_tag
AS RESTRICTIVE
FOR SELECT
TO anon, authenticated
USING (
    EXISTS (
        SELECT 1
        FROM public.product AS tagged_product
        WHERE tagged_product.id = product_search_tag.product_id
          AND tagged_product.lifecycle_state = 'published'::public.product_state
    )
);

DO $search_tags_postflight$
DECLARE
    tag_table oid := 'public.product_search_tag'::pg_catalog.regclass;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS table_metadata
        WHERE table_metadata.oid = tag_table
          AND table_metadata.relrowsecurity
          AND pg_catalog.pg_get_userbyid(table_metadata.relowner) = 'postgres'
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags postflight: table, owner or RLS mismatch';
    END IF;

    IF (
        SELECT pg_catalog.count(*)
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'product_search_tag'
    ) <> 3 THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags postflight: policy inventory mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'product_search_tag'
          AND policy.policyname = 'product_search_tag_published_only_guard'
          AND policy.permissive = 'RESTRICTIVE'
          AND policy.cmd = 'SELECT'
          AND policy.roles = ARRAY['anon', 'authenticated']::name[]
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags postflight: restrictive guard mismatch';
    END IF;

    IF NOT pg_catalog.has_table_privilege('anon', tag_table, 'SELECT')
       OR NOT pg_catalog.has_table_privilege('authenticated', tag_table, 'SELECT')
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags postflight: clients cannot read';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES ('anon'::name), ('authenticated'::name), ('service_role'::name)
        ) AS client(role_name)
        CROSS JOIN (
            VALUES ('INSERT'::text), ('UPDATE'::text), ('DELETE'::text)
        ) AS write_privilege(name)
        WHERE pg_catalog.has_table_privilege(
            client.role_name, tag_table, write_privilege.name
        )
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags postflight: a client can write a guess';
    END IF;
END
$search_tags_postflight$;

COMMIT;
