/*
Phase 4A catalogue quality audit -- READ ONLY.

Twelve independent SELECT-only statements that measure how far the deployed
catalogue is from the normalization targets in the master plan (dimensions,
units, materials, colours, styles, finishes, room types, capacity, categories,
synonyms). Run each numbered statement separately in the Supabase SQL Editor and
export the result with Download CSV to docs/evidence/phase-4a/section-NN.csv.

Every statement returns aggregates or catalogue vocabulary only. No statement
returns a product name, description, seller business name, image URL, user
identifier, or row UUID. Do not add transaction, procedural, dynamic, or
mutation statements. Nothing here changes the database.

Sections 02 to 12 reference only columns the Phase 3.1 live smoke verified:
product(id, name, description, price, discount_price, width_cm, height_cm,
depth_cm, weight_kg, materials, lifecycle_state, category_id,
marketplace_party_id), category(id, name, is_active), marketplace_party(id,
approval_state), product_color(id, product_id, color_value, stock_quantity,
display_order), product_image(id, product_id, product_color_id, image_url,
is_primary, display_order), product_enrichment_assignment(product_id,
attribute_id, confirmation_state), product_enrichment_attribute(id,
attribute_kind, attribute_value). Section 01 reports every other column so the
Phase 4B normalization design can use the complete schema.
*/

-- 01. Exact column signature of the seven catalogue tables.
SELECT
    relation.relname::text AS table_name,
    attribute.attnum::integer AS ordinal_position,
    attribute.attname::text AS column_name,
    replace(
        pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
        'public.',
        ''
    ) AS formatted_type,
    attribute.attnotnull AS is_not_null,
    replace(
        replace(
            pg_catalog.pg_get_expr(column_default.adbin, column_default.adrelid, false),
            'public.',
            ''
        ),
        'pg_catalog.',
        ''
    ) AS default_expression,
    attribute.attgenerated::text AS generated_kind
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
JOIN pg_catalog.pg_attribute AS attribute
    ON attribute.attrelid = relation.oid
LEFT JOIN pg_catalog.pg_attrdef AS column_default
    ON column_default.adrelid = attribute.attrelid
   AND column_default.adnum = attribute.attnum
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
  AND relation.relname IN (
      'product',
      'product_color',
      'product_image',
      'product_3d_model',
      'category',
      'product_enrichment_attribute',
      'product_enrichment_assignment'
  )
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY relation.relname, attribute.attnum;


-- 02. Product counts by lifecycle state and the recommendation-eligible subset.
WITH eligible AS (
    SELECT product.id
    FROM public.product
    JOIN public.marketplace_party AS seller
        ON seller.id = product.marketplace_party_id
    JOIN public.category
        ON category.id = product.category_id
    WHERE product.lifecycle_state = 'published'::public.product_state
      AND seller.approval_state = 'approved'::public.party_approval_state
      AND category.is_active
      AND EXISTS (
          SELECT 1
          FROM public.product_color AS colour
          WHERE colour.product_id = product.id
            AND colour.stock_quantity > 0
      )
)
SELECT
    'lifecycle_state'::text AS measure,
    product.lifecycle_state::text AS bucket,
    count(*)::bigint AS product_count
FROM public.product
GROUP BY product.lifecycle_state
UNION ALL
SELECT
    'eligible'::text AS measure,
    'recommendation_eligible'::text AS bucket,
    count(*)::bigint AS product_count
FROM eligible
ORDER BY measure, bucket;


-- 03. Measurement completeness and spread for eligible products (centimetres, kilograms).
WITH eligible AS (
    SELECT product.width_cm, product.height_cm, product.depth_cm, product.weight_kg
    FROM public.product
    JOIN public.marketplace_party AS seller
        ON seller.id = product.marketplace_party_id
    JOIN public.category
        ON category.id = product.category_id
    WHERE product.lifecycle_state = 'published'::public.product_state
      AND seller.approval_state = 'approved'::public.party_approval_state
      AND category.is_active
      AND EXISTS (
          SELECT 1
          FROM public.product_color AS colour
          WHERE colour.product_id = product.id
            AND colour.stock_quantity > 0
      )
),
measures(measure, value) AS (
    SELECT 'width_cm', width_cm FROM eligible
    UNION ALL
    SELECT 'height_cm', height_cm FROM eligible
    UNION ALL
    SELECT 'depth_cm', depth_cm FROM eligible
    UNION ALL
    SELECT 'weight_kg', weight_kg FROM eligible
)
SELECT
    measure,
    count(*)::bigint AS product_count,
    count(*) FILTER (WHERE value IS NULL)::bigint AS null_count,
    count(*) FILTER (WHERE value <= 0)::bigint AS non_positive_count,
    min(value) AS minimum,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS median,
    max(value) AS maximum,
    count(*) FILTER (WHERE value > 1000)::bigint AS over_1000_count
FROM measures
GROUP BY measure
ORDER BY measure;


-- 04. Price sanity across all published products.
SELECT
    count(*)::bigint AS published_count,
    count(*) FILTER (WHERE price IS NULL OR price <= 0)::bigint AS non_positive_price_count,
    count(*) FILTER (WHERE discount_price IS NOT NULL)::bigint AS discounted_count,
    count(*) FILTER (WHERE discount_price IS NOT NULL AND discount_price >= price)::bigint
        AS discount_not_below_price_count,
    count(*) FILTER (WHERE discount_price IS NOT NULL AND discount_price <= 0)::bigint
        AS non_positive_discount_count,
    min(price) AS minimum_price,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS median_price,
    max(price) AS maximum_price
FROM public.product
WHERE lifecycle_state = 'published'::public.product_state;


-- 05. Material vocabulary: distinct lower-cased tokens with product counts.
WITH tokens AS (
    SELECT
        product.id AS product_id,
        lower(btrim(material)) AS material_token
    FROM public.product
    CROSS JOIN LATERAL unnest(product.materials) AS material
    WHERE product.lifecycle_state = 'published'::public.product_state
)
SELECT
    'token'::text AS row_kind,
    material_token AS material,
    count(DISTINCT product_id)::bigint AS product_count
FROM tokens
GROUP BY material_token
UNION ALL
SELECT
    'summary'::text AS row_kind,
    'products_without_materials'::text AS material,
    count(*)::bigint AS product_count
FROM public.product
WHERE lifecycle_state = 'published'::public.product_state
  AND (materials IS NULL OR cardinality(materials) = 0)
ORDER BY row_kind DESC, product_count DESC, material;


-- 06. Category inventory with product counts per state.
SELECT
    category.name AS category_name,
    category.is_active,
    count(product.id)::bigint AS total_products,
    count(product.id) FILTER (
        WHERE product.lifecycle_state = 'published'::public.product_state
    )::bigint AS published_products,
    count(product.id) FILTER (
        WHERE product.lifecycle_state = 'published'::public.product_state
          AND EXISTS (
              SELECT 1
              FROM public.product_color AS colour
              WHERE colour.product_id = product.id
                AND colour.stock_quantity > 0
          )
    )::bigint AS in_stock_published_products
FROM public.category
LEFT JOIN public.product
    ON product.category_id = category.id
GROUP BY category.id, category.name, category.is_active
ORDER BY category.is_active DESC, total_products DESC, category.name;


-- 07. Colour vocabulary and stock distribution for published products.
WITH colours AS (
    SELECT
        lower(btrim(colour.color_value)) AS colour_token,
        colour.stock_quantity,
        colour.product_id
    FROM public.product_color AS colour
    JOIN public.product
        ON product.id = colour.product_id
    WHERE product.lifecycle_state = 'published'::public.product_state
)
SELECT
    'token'::text AS row_kind,
    colour_token AS colour,
    count(*)::bigint AS colour_rows,
    count(DISTINCT product_id)::bigint AS product_count,
    count(*) FILTER (WHERE stock_quantity > 0)::bigint AS in_stock_rows
FROM colours
GROUP BY colour_token
UNION ALL
SELECT
    'summary'::text AS row_kind,
    'published_products_without_stock'::text AS colour,
    count(*)::bigint AS colour_rows,
    count(*)::bigint AS product_count,
    0::bigint AS in_stock_rows
FROM public.product
WHERE product.lifecycle_state = 'published'::public.product_state
  AND NOT EXISTS (
      SELECT 1
      FROM public.product_color AS colour
      WHERE colour.product_id = product.id
        AND colour.stock_quantity > 0
  )
ORDER BY row_kind DESC, product_count DESC, colour;


-- 08. Image coverage for published products; no URL is returned.
WITH per_product AS (
    SELECT
        product.id AS product_id,
        count(image.id)::integer AS image_count,
        count(image.id) FILTER (WHERE image.is_primary)::integer AS primary_count,
        count(image.id) FILTER (
            WHERE image.image_url NOT LIKE 'https://%'
        )::integer AS non_https_count,
        count(image.id) FILTER (
            WHERE image.product_color_id IS NOT NULL
        )::integer AS colour_linked_count
    FROM public.product
    LEFT JOIN public.product_image AS image
        ON image.product_id = product.id
    WHERE product.lifecycle_state = 'published'::public.product_state
    GROUP BY product.id
)
SELECT
    count(*)::bigint AS published_products,
    count(*) FILTER (WHERE image_count = 0)::bigint AS without_images,
    count(*) FILTER (WHERE primary_count = 0)::bigint AS without_primary,
    count(*) FILTER (WHERE primary_count > 1)::bigint AS multiple_primary,
    count(*) FILTER (WHERE non_https_count > 0)::bigint AS with_non_https_urls,
    count(*) FILTER (WHERE colour_linked_count > 0)::bigint AS with_colour_linked_images,
    min(image_count)::integer AS minimum_images,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY image_count) AS median_images,
    max(image_count)::integer AS maximum_images
FROM per_product;


-- 09. Enrichment attribute kinds: inferred value types and confirmation coverage.
-- attribute_value is a text column (confirmed live 2026-09-16), so the type is
-- inferred from the text shape rather than read from a JSON type.
SELECT
    attribute.attribute_kind AS kind,
    CASE
        WHEN attribute.attribute_value IS NULL THEN 'null'
        WHEN btrim(attribute.attribute_value) ~ '^-?[0-9]+(\.[0-9]+)?$' THEN 'number'
        WHEN lower(btrim(attribute.attribute_value)) IN ('true', 'false') THEN 'boolean'
        WHEN btrim(attribute.attribute_value) ~ '^[\[{]' THEN 'json_like'
        ELSE 'string'
    END AS value_type,
    count(DISTINCT attribute.id)::bigint AS attribute_count,
    count(assignment.product_id) FILTER (
        WHERE assignment.confirmation_state = 'party_confirmed'
    )::bigint AS confirmed_assignments,
    count(assignment.product_id) FILTER (
        WHERE assignment.confirmation_state = 'ai_proposed'
    )::bigint AS proposed_assignments,
    count(DISTINCT assignment.product_id) FILTER (
        WHERE assignment.confirmation_state = 'party_confirmed'
    )::bigint AS confirmed_products
FROM public.product_enrichment_attribute AS attribute
LEFT JOIN public.product_enrichment_assignment AS assignment
    ON assignment.attribute_id = attribute.id
GROUP BY attribute.attribute_kind, 2
ORDER BY attribute.attribute_kind, value_type;


-- 10. Enrichment vocabulary: distinct values per kind, bounded.
SELECT
    attribute.attribute_kind AS kind,
    lower(btrim(attribute.attribute_value)) AS value_text,
    count(DISTINCT assignment.product_id) FILTER (
        WHERE assignment.confirmation_state = 'party_confirmed'
    )::bigint AS confirmed_products,
    count(DISTINCT assignment.product_id)::bigint AS assigned_products
FROM public.product_enrichment_attribute AS attribute
LEFT JOIN public.product_enrichment_assignment AS assignment
    ON assignment.attribute_id = attribute.id
WHERE attribute.attribute_value IS NOT NULL
  AND btrim(attribute.attribute_value) !~ '^[\[{]'
GROUP BY attribute.attribute_kind, lower(btrim(attribute.attribute_value))
ORDER BY attribute.attribute_kind, assigned_products DESC, value_text
LIMIT 500;


-- 11. Text field quality for published products; lengths and duplicates only.
WITH published AS (
    SELECT id, name, description, marketplace_party_id
    FROM public.product
    WHERE lifecycle_state = 'published'::public.product_state
),
duplicate_names AS (
    SELECT count(*)::bigint AS duplicate_groups
    FROM (
        SELECT lower(btrim(name)) AS normalized_name, marketplace_party_id
        FROM published
        GROUP BY lower(btrim(name)), marketplace_party_id
        HAVING count(*) > 1
    ) AS grouped
)
SELECT
    count(*)::bigint AS published_products,
    count(*) FILTER (WHERE length(btrim(name)) < 3)::bigint AS short_names,
    count(*) FILTER (WHERE description IS NULL OR length(btrim(description)) = 0)::bigint
        AS missing_descriptions,
    count(*) FILTER (WHERE length(btrim(description)) < 40)::bigint AS short_descriptions,
    count(*) FILTER (WHERE name ~ '[0-9]+ *(cm|mm|m|kg)')::bigint AS names_with_units,
    count(*) FILTER (WHERE description ~ '[0-9]+ *(cm|mm|m|kg)')::bigint
        AS descriptions_with_units,
    count(*) FILTER (WHERE name ~ '[؀-ۿ]')::bigint AS names_with_arabic,
    count(*) FILTER (WHERE description ~ '[؀-ۿ]')::bigint
        AS descriptions_with_arabic,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY length(name)) AS median_name_length,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY length(coalesce(description, '')))
        AS median_description_length,
    (SELECT duplicate_groups FROM duplicate_names) AS duplicate_name_groups
FROM published;


-- 12. Audit completeness: every catalogue table exists with RLS enabled.
WITH expected(table_name) AS (
    VALUES
        ('product'),
        ('product_color'),
        ('product_image'),
        ('product_3d_model'),
        ('category'),
        ('product_enrichment_attribute'),
        ('product_enrichment_assignment'),
        ('marketplace_party')
),
actual AS (
    SELECT relation.relname::text AS table_name, relation.relrowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p')
)
SELECT
    'catalogue_tables_present_with_rls'::text AS check_name,
    (SELECT count(*) FROM expected)::bigint AS expected_count,
    count(actual.table_name) FILTER (WHERE actual.relrowsecurity)::bigint AS actual_count,
    (SELECT count(*) FROM expected)
        - count(actual.table_name) FILTER (WHERE actual.relrowsecurity) AS failed_count,
    count(actual.table_name) FILTER (WHERE actual.relrowsecurity)
        = (SELECT count(*) FROM expected) AS check_passed
FROM expected
LEFT JOIN actual
    ON actual.table_name = expected.table_name;
