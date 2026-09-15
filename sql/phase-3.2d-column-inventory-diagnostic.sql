/*
Phase 3.2D read-only column inventory diagnostic.

Four independent SELECT-only catalog statements. Run each numbered statement
separately in the Supabase SQL Editor and export its result as CSV to:

  01 -> docs/evidence/phase-3.2d/column-inventory.csv
  02 -> docs/evidence/phase-3.2d/column-privileges.csv
  03 -> docs/evidence/phase-3.2d/state-enums.csv
  04 -> docs/evidence/phase-3.2d/constraints.csv

They read pg_catalog only and return no application rows, identifiers,
credentials, or endpoint values. Do not add transaction, procedural, dynamic,
or mutation statements. Nothing here changes the database.
*/

-- 01. Exact column signature of the nine Phase 3.2D candidate tables, in the
-- same shape as the Phase 3.2C furnishing_request inventory.
SELECT
    relation.relname::text AS table_name,
    attribute.attnum::integer AS ordinal_position,
    attribute.attname::text AS column_name,
    replace(
        pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
        'public.',
        ''
    ) AS formatted_type,
    attribute.atttypid::pg_catalog.regtype::text AS type_name,
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
    attribute.attidentity::text AS identity_kind,
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
      'customer_profile',
      'design',
      'design_version',
      'design_product_reference',
      'party_capability',
      'service_request',
      'purchase_order',
      'order_line_item',
      'review',
      'address',
      'cart',
      'cart_line',
      'saved_space',
      'custom_offering',
      'offer_line_item',
      'furnishing_request_design_version',
      'furnishing_request',
      'marketplace_party'
  )
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY relation.relname, attribute.attnum;


-- 02. Effective per-column SELECT, INSERT, and UPDATE privilege for the three
-- API roles, plus the table-level privilege that would mask column grants.
SELECT
    relation.relname::text AS table_name,
    attribute.attnum::integer AS ordinal_position,
    attribute.attname::text AS column_name,
    api_role.role_name,
    pg_catalog.has_table_privilege(
        api_role.role_name, relation.oid, 'SELECT'
    ) AS table_select,
    pg_catalog.has_table_privilege(
        api_role.role_name, relation.oid, 'INSERT'
    ) AS table_insert,
    pg_catalog.has_table_privilege(
        api_role.role_name, relation.oid, 'UPDATE'
    ) AS table_update,
    pg_catalog.has_table_privilege(
        api_role.role_name, relation.oid, 'DELETE'
    ) AS table_delete,
    pg_catalog.has_column_privilege(
        api_role.role_name, relation.oid, attribute.attnum, 'SELECT'
    ) AS column_select,
    pg_catalog.has_column_privilege(
        api_role.role_name, relation.oid, attribute.attnum, 'INSERT'
    ) AS column_insert,
    pg_catalog.has_column_privilege(
        api_role.role_name, relation.oid, attribute.attnum, 'UPDATE'
    ) AS column_update,
    attribute.attacl IS NOT NULL AS has_column_acl
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
JOIN pg_catalog.pg_attribute AS attribute
    ON attribute.attrelid = relation.oid
CROSS JOIN (
    VALUES
        ('anon'::text),
        ('authenticated'::text),
        ('service_role'::text)
) AS api_role(role_name)
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
  AND relation.relname IN (
      'customer_profile',
      'design',
      'design_version',
      'design_product_reference',
      'party_capability',
      'service_request',
      'purchase_order',
      'order_line_item',
      'review',
      'address',
      'cart',
      'cart_line',
      'saved_space',
      'custom_offering',
      'offer_line_item',
      'furnishing_request_design_version',
      'furnishing_request',
      'marketplace_party'
  )
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY relation.relname, attribute.attnum, api_role.role_name;


-- 03. Every public enum type used by a column of the candidate tables, with
-- its complete ordered label set. This is the state model input for Pack B.
SELECT
    enum_type.typname::text AS enum_type_name,
    enum_label.enumsortorder AS label_order,
    enum_label.enumlabel::text AS label,
    (
        SELECT string_agg(
            relation.relname::text || '.' || attribute.attname::text,
            ', '
            ORDER BY relation.relname, attribute.attnum
        )
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation
            ON relation.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace AS relation_namespace
            ON relation_namespace.oid = relation.relnamespace
        WHERE attribute.atttypid = enum_type.oid
          AND relation_namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p')
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) AS used_by_columns
FROM pg_catalog.pg_type AS enum_type
JOIN pg_catalog.pg_namespace AS type_namespace
    ON type_namespace.oid = enum_type.typnamespace
JOIN pg_catalog.pg_enum AS enum_label
    ON enum_label.enumtypid = enum_type.oid
WHERE type_namespace.nspname = 'public'
  AND enum_type.typtype = 'e'
  AND EXISTS (
      SELECT 1
      FROM pg_catalog.pg_attribute AS attribute
      JOIN pg_catalog.pg_class AS relation
          ON relation.oid = attribute.attrelid
      JOIN pg_catalog.pg_namespace AS relation_namespace
          ON relation_namespace.oid = relation.relnamespace
      WHERE attribute.atttypid = enum_type.oid
        AND relation_namespace.nspname = 'public'
        AND relation.relname IN (
            'customer_profile',
            'design',
            'design_version',
            'design_product_reference',
            'party_capability',
            'service_request',
            'purchase_order',
            'order_line_item',
            'review',
            'furnishing_request',
            'offer',
            'marketplace_party',
            'address',
            'cart',
            'cart_line',
            'saved_space',
            'custom_offering',
            'offer_line_item',
            'furnishing_request_design_version'
        )
        AND attribute.attnum > 0
        AND NOT attribute.attisdropped
  )
ORDER BY enum_type.typname, enum_label.enumsortorder;


-- 04. Primary-key, unique, foreign-key, and check constraints on the candidate
-- tables. Answers one-profile-per-user, address and product references, and
-- delete behaviour for referenced rows.
SELECT
    relation.relname::text AS table_name,
    constraint_row.conname::text AS constraint_name,
    constraint_row.contype::text AS constraint_kind,
    pg_catalog.pg_get_constraintdef(constraint_row.oid, true) AS definition,
    COALESCE(referenced.relname::text, '') AS referenced_table,
    CASE constraint_row.confdeltype
        WHEN 'a' THEN 'no action'
        WHEN 'r' THEN 'restrict'
        WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set null'
        WHEN 'd' THEN 'set default'
        ELSE ''
    END AS on_delete
FROM pg_catalog.pg_constraint AS constraint_row
JOIN pg_catalog.pg_class AS relation
    ON relation.oid = constraint_row.conrelid
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
LEFT JOIN pg_catalog.pg_class AS referenced
    ON referenced.oid = constraint_row.confrelid
WHERE namespace.nspname = 'public'
  AND relation.relname IN (
      'customer_profile',
      'design',
      'design_version',
      'design_product_reference',
      'party_capability',
      'service_request',
      'purchase_order',
      'order_line_item',
      'review',
      'address',
      'cart',
      'cart_line',
      'saved_space',
      'custom_offering',
      'offer_line_item',
      'furnishing_request_design_version',
      'furnishing_request',
      'marketplace_party'
  )
ORDER BY relation.relname, constraint_row.contype, constraint_row.conname;
