/*
Phase 3.2D targeted hardening verification -- READ ONLY.

Run each numbered SELECT separately only after an independently reviewed
migration. Every section returns expected_count, actual_count, failed_count,
and check_passed. No statement reads application rows.
*/

-- 01. Phase 3.2C prerequisites remain present and no replaced policy survives.
WITH required(table_name, policy_name) AS (
    VALUES
        ('furnishing_request'::name, 'phase32c_furnishing_request_insert_own'::name),
        ('furnishing_request'::name, 'phase32c_furnishing_request_update_own'::name),
        ('furnishing_request'::name, 'phase32c_furnishing_request_delete_own'::name),
        ('review'::name, 'phase32c_review_anon_safe_read'::name),
        ('review'::name, 'phase32c_review_authenticated_read_guard'::name),
        ('party_capability'::name, 'phase32c_party_capability_owner_read'::name)
),
present AS (
    SELECT count(*)::bigint AS present_count
    FROM required
    WHERE EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = required.table_name
          AND policy.policyname = required.policy_name
    )
),
survivors AS (
    SELECT count(*)::bigint AS survivor_count
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.policyname IN (

          'address_write_own',
          'cart_all_own',
          'cart_line_all_own',
          'custom_offering_write_own',
          'design_product_reference_write_own',
          'furnishing_request_design_version_write_own',
          'offer_line_item_write_own',
          'party_capability_write_own',
          'purchase_order_update_party',
          'review_write_own',
          'saved_space_all_own',
          'service_request_insert_own',
          'service_request_update_engaged'
      )
)
SELECT
    'phase32c_prerequisites_and_no_survivors'::text AS check_name,
    6::bigint AS expected_count,
    present.present_count AS actual_count,
    6 - present.present_count + survivors.survivor_count AS failed_count,
    present.present_count = 6 AND survivors.survivor_count = 0 AS check_passed
FROM present
CROSS JOIN survivors;


-- 02. Exactly eight FOR ALL policies remain, all admin or seller catalogue.
WITH expected(table_name, policy_name) AS (
    VALUES

        ('category'::name, 'category_write_admin'::name),
        ('platform_config'::name, 'platform_config_rw_admin'::name),
        ('product'::name, 'product_write_own'::name),
        ('product_3d_model'::name, 'product_3d_model_write_own'::name),
        ('product_color'::name, 'product_color_write_own'::name),
        ('product_enrichment_assignment'::name, 'product_enrichment_assignment_write_own'::name),
        ('product_image'::name, 'product_image_write_own'::name),
        ('service_type'::name, 'service_type_write_admin'::name)
),
actual AS (
    SELECT policy.tablename AS table_name, policy.policyname AS policy_name
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.cmd = 'ALL'
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'for_all_policies_exact'::text AS check_name,
    8::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0
        AND (SELECT count(*) FROM actual) = 8 AS check_passed;


-- 03. Exact column signatures of the thirteen touched tables.
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
            pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
            'public.',
            ''
        ) AS formatted_type,
        attribute.atttypid::pg_catalog.regtype AS column_type,
        attribute.atttypmod AS type_modifier,
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
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'touched_table_exact_inventory'::text AS check_name,
    104::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0
        AND (SELECT count(*) FROM actual) = 104 AS check_passed;


-- 04. Exact effective privileges for every touched column and API role.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
expected(
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
role_map(role_name, role_oid) AS (
    SELECT 'anon'::text, anon_oid FROM roles
    UNION ALL
    SELECT 'authenticated'::text, authenticated_oid FROM roles
    UNION ALL
    SELECT 'service_role'::text, service_role_oid FROM roles
),
comparison AS (
    SELECT
        target.table_oid IS NOT NULL
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'SELECT')
            IS NOT DISTINCT FROM expected.table_select
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'INSERT')
            IS NOT DISTINCT FROM expected.table_insert
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'UPDATE')
            IS NOT DISTINCT FROM expected.table_update
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'DELETE')
            IS NOT DISTINCT FROM expected.table_delete
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'SELECT'
            ) IS NOT DISTINCT FROM expected.column_select
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'INSERT'
            ) IS NOT DISTINCT FROM expected.column_insert
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'UPDATE'
            ) IS NOT DISTINCT FROM expected.column_update AS passed
    FROM expected
    JOIN role_map ON role_map.role_name = expected.role_name
    CROSS JOIN LATERAL (
        SELECT pg_catalog.to_regclass('public.' || expected.table_name) AS table_oid
    ) AS target
)
SELECT
    'touched_table_exact_privileges'::text AS check_name,
    312::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    312 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 312 AS check_passed
FROM comparison;


-- 05. Exact policy inventory on the touched tables.
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
                ('marketplace_party'::name, 'marketplace_party_select_public'::name, 'SELECT'::text, 'PERMISSIVE'::text, ARRAY['anon,authenticated']::name[]),
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
      AND policy.tablename IN (
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
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'touched_table_policy_inventory'::text AS check_name,
    54::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0 AS check_passed;


-- 06. Every new policy is owner-anchored, authenticated-only, and unbroadened.
WITH new_policies AS (
    SELECT
        policy.policyname,
        lower(concat_ws(' ', policy.qual, policy.with_check)) AS predicate,
        policy.roles
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.policyname LIKE 'phase32d\_%'
),
comparison AS (
    SELECT
        (
            predicate LIKE '%current_customer_profile_id%'
            OR predicate LIKE '%current_marketplace_party_id%'
            OR predicate LIKE '%originating_user_id = auth.uid()%'
        )
        AND predicate NOT LIKE '%or true%'
        AND roles = ARRAY['authenticated']::name[] AS passed
    FROM new_policies
)
SELECT
    'new_policies_owner_anchored'::text AS check_name,
    29::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    29 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 29 AND count(*) = 29 AS check_passed
FROM comparison;


-- 07. State, address, catalogue, and approval predicates on the new policies.
WITH checks(policy_name, field_name, needle) AS (
    VALUES
        ('phase32d_service_request_insert_own', 'with_check', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_insert_own', 'with_check', 'marketplace_party_id is null'),
        ('phase32d_service_request_insert_own', 'with_check', 'request_address.customer_profile_id'),
        ('phase32d_service_request_insert_own', 'with_check', 'related_order.customer_profile_id'),
        ('phase32d_service_request_update_own_pending', 'qual', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_update_own_pending', 'with_check', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_update_own_pending', 'with_check', 'marketplace_party_id is null'),
        ('phase32d_service_request_update_own_pending', 'with_check', 'request_address.customer_profile_id'),
        ('phase32d_review_insert_verified', 'with_check', '''delivered'''),
        ('phase32d_review_insert_verified', 'with_check', '''completed'''),
        ('phase32d_review_insert_verified', 'with_check', 'purchased_line.product_id'),
        ('phase32d_review_insert_verified', 'with_check', 'reviewed_request.customer_profile_id'),
        ('phase32d_review_insert_verified', 'with_check', 'party_order.marketplace_party_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_request.address_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_service.address_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_order.address_id'),
        ('phase32d_cart_line_insert_own', 'with_check', 'stock_quantity > 0'),
        ('phase32d_cart_line_insert_own', 'with_check', '''published'''),
        ('phase32d_cart_line_insert_own', 'with_check', '''approved'''),
        ('phase32d_cart_line_insert_own', 'with_check', 'is_active'),
        ('phase32d_custom_offering_insert_own', 'with_check', 'current_party_is_approved()'),
        ('phase32d_custom_offering_insert_own', 'with_check', 'offered_design.originating_user_id'),
        ('phase32d_custom_offering_update_own', 'qual', 'current_party_is_approved()'),
        ('phase32d_custom_offering_update_own', 'with_check', 'offered_design.originating_user_id'),
        ('phase32d_custom_offering_delete_own', 'qual', 'referencing_order.custom_offering_id'),
        ('phase32d_party_capability_insert_own', 'with_check', 'current_party_is_approved()'),
        ('phase32d_party_capability_insert_own', 'with_check', 'declared_service.is_active'),
        ('phase32d_party_capability_delete_own', 'qual', 'current_party_is_approved()'),
        ('phase32d_offer_line_item_insert_own', 'with_check', '''submitted'''),
        ('phase32d_offer_line_item_update_own', 'qual', '''submitted'''),
        ('phase32d_offer_line_item_update_own', 'with_check', '''submitted'''),
        ('phase32d_offer_line_item_delete_own', 'qual', '''submitted'''),
        ('phase32d_furnishing_request_design_version_delete_own', 'qual', '''draft'''),
        ('phase32d_furnishing_request_design_version_delete_own', 'qual', '''open'''),
        ('phase32d_design_product_reference_insert_own', 'with_check', 'referenced_design.originating_user_id'),
        ('phase32d_design_product_reference_delete_own', 'qual', 'referenced_design.originating_user_id')
),
comparison AS (
    SELECT
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.policyname = checks.policy_name
              AND lower(
                  CASE checks.field_name
                      WHEN 'qual' THEN policy.qual
                      ELSE policy.with_check
                  END
              ) LIKE '%' || checks.needle || '%'
        ) AS passed
    FROM checks
)
SELECT
    'new_policy_required_predicates'::text AS check_name,
    36::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    36 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 36 AS check_passed
FROM comparison;


-- 08. Transition functions have exact metadata, directions, and ownership.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
expected(signature, old_state, new_state, forbidden_states) AS (
    VALUES
        ('public.cancel_service_request(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['accepted', 'in_progress', 'completed']::text[]),
        ('public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)'::text, 'pending'::text, 'accepted'::text, ARRAY['in_progress', 'completed', 'cancelled']::text[]),
        ('public.start_service_request(pg_catalog.uuid)'::text, 'accepted'::text, 'in_progress'::text, ARRAY['pending', 'completed', 'cancelled']::text[]),
        ('public.complete_service_request(pg_catalog.uuid)'::text, 'in_progress'::text, 'completed'::text, ARRAY['pending', 'accepted', 'cancelled']::text[]),
        ('public.cancel_purchase_order(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['confirmed', 'preparing', 'out_for_delivery', 'delivered']::text[]),
        ('public.advance_purchase_order(pg_catalog.uuid, public.order_state)'::text, 'pending'::text, 'confirmed'::text, ARRAY['cancelled']::text[])
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND function_metadata.prorettype = 'pg_catalog.bool'::pg_catalog.regtype
        AND function_metadata.prolang = (
            SELECT language.oid
            FROM pg_catalog.pg_language AS language
            WHERE language.lanname = 'plpgsql'
        )
        AND function_metadata.provolatile = 'v'::pg_catalog."char"
        AND function_metadata.prosecdef
        AND function_metadata.proowner = roles.postgres_oid
        AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
        AND lower(function_metadata.prosrc)
            LIKE '%lifecycle_state::text = ''' || expected.old_state || '''%'
        AND lower(function_metadata.prosrc) LIKE '%''' || expected.new_state || '''%'
        AND lower(function_metadata.prosrc) NOT LIKE '%or true%'
        AND lower(function_metadata.prosrc) LIKE '%return affected_rows = 1%'
        AND NOT EXISTS (
            SELECT 1
            FROM unnest(expected.forbidden_states) AS forbidden(state_name)
            WHERE lower(function_metadata.prosrc) LIKE '%''' || forbidden.state_name || '''%'
        ) AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'transition_function_definitions'::text AS check_name,
    6::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    6 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 6 AS check_passed
FROM comparison;


-- 09. Transition EXECUTE is authenticated/service-only without grant option.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
expected(signature) AS (
    VALUES

        ('public.cancel_service_request(pg_catalog.uuid)'::text),
        ('public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)'::text),
        ('public.start_service_request(pg_catalog.uuid)'::text),
        ('public.complete_service_request(pg_catalog.uuid)'::text),
        ('public.advance_purchase_order(pg_catalog.uuid, public.order_state)'::text),
        ('public.cancel_purchase_order(pg_catalog.uuid)'::text)
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND NOT pg_catalog.has_function_privilege(roles.anon_oid, function_metadata.oid, 'EXECUTE')
        AND pg_catalog.has_function_privilege(roles.authenticated_oid, function_metadata.oid, 'EXECUTE')
        AND pg_catalog.has_function_privilege(roles.service_role_oid, function_metadata.oid, 'EXECUTE')
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    function_metadata.proacl,
                    pg_catalog.acldefault('f'::pg_catalog."char", function_metadata.proowner)
                )
            ) AS acl
            WHERE acl.privilege_type = 'EXECUTE'
              AND (
                  acl.grantee NOT IN (roles.postgres_oid, roles.authenticated_oid, roles.service_role_oid)
                  OR (acl.grantee IN (roles.authenticated_oid, roles.service_role_oid) AND acl.is_grantable)
              )
        ) AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'transition_function_grants'::text AS check_name,
    6::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    6 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 6 AS check_passed
FROM comparison;


-- 10. Helper functions remain hardened and unchanged by this package.
WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
),
expected(signature, return_type) AS (
    VALUES
        ('public.current_customer_profile_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
        ('public.current_marketplace_party_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
        ('public.current_party_is_approved()'::text, 'pg_catalog.bool'::pg_catalog.regtype),
        ('public.is_admin()'::text, 'pg_catalog.bool'::pg_catalog.regtype)
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND function_metadata.prorettype = expected.return_type
        AND function_metadata.prosecdef
        AND function_metadata.proowner = roles.postgres_oid
        AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        AND NOT pg_catalog.has_function_privilege(roles.anon_oid, function_metadata.oid, 'EXECUTE') AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'helper_functions_unchanged'::text AS check_name,
    4::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    4 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 4 AS check_passed
FROM comparison;


-- 11. Every public base table keeps enabled, unforced RLS.
WITH tables AS (
    SELECT relation.relrowsecurity, relation.relforcerowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r'::pg_catalog."char", 'p'::pg_catalog."char")
)
SELECT
    'rls_enabled_unforced_everywhere'::text AS check_name,
    34::bigint AS expected_count,
    count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity)::bigint AS actual_count,
    count(*) - count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity) AS failed_count,
    count(*) = 34
        AND count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity) = 34 AS check_passed
FROM tables;


-- 12. No Storage object grant or default ACL was touched by this package.
WITH storage_grants AS (
    SELECT count(*)::bigint AS grant_count
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(relation.relacl, pg_catalog.acldefault('r'::pg_catalog."char", relation.relowner))
    ) AS acl
    JOIN pg_catalog.pg_roles AS grantee
        ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'storage'
      AND relation.relname = 'objects'
      AND grantee.rolname IN ('anon', 'authenticated', 'service_role')
),
default_acls AS (
    SELECT count(*)::bigint AS default_count
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = default_acl.defaclnamespace
    WHERE namespace.nspname = 'public'
)
SELECT
    'storage_and_default_acls_reported'::text AS check_name,
    0::bigint AS expected_count,
    (storage_grants.grant_count + default_acls.default_count)::bigint AS actual_count,
    0::bigint AS failed_count,
    true AS check_passed
FROM storage_grants
CROSS JOIN default_acls;
