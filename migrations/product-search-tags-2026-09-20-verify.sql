-- READ ONLY. Search-tag verification: every row must show passed = true.
SELECT check_name, passed
FROM (
    VALUES
        (
            'the table exists, is owned by postgres and has RLS on',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS table_metadata
                WHERE table_metadata.oid =
                      pg_catalog.to_regclass('public.product_search_tag')
                  AND table_metadata.relrowsecurity
                  AND pg_catalog.pg_get_userbyid(table_metadata.relowner) = 'postgres'
            )
        ),
        (
            'clients may read tags',
            pg_catalog.has_table_privilege(
                'anon', 'public.product_search_tag', 'SELECT')
            AND pg_catalog.has_table_privilege(
                'authenticated', 'public.product_search_tag', 'SELECT')
        ),
        (
            'no client role can write a guess',
            NOT EXISTS (
                SELECT 1
                FROM (
                    VALUES ('anon'::name), ('authenticated'::name), ('service_role'::name)
                ) AS client(role_name)
                CROSS JOIN (
                    VALUES ('INSERT'::text), ('UPDATE'::text), ('DELETE'::text)
                ) AS write_privilege(name)
                WHERE pg_catalog.has_table_privilege(
                    client.role_name,
                    'public.product_search_tag',
                    write_privilege.name
                )
            )
        ),
        (
            'exactly the three read policies exist',
            (
                SELECT pg_catalog.count(*)
                FROM pg_catalog.pg_policies AS policy
                WHERE policy.schemaname = 'public'
                  AND policy.tablename = 'product_search_tag'
            ) = 3
        ),
        (
            'the restrictive guard covers both client roles',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_policies AS policy
                WHERE policy.schemaname = 'public'
                  AND policy.tablename = 'product_search_tag'
                  AND policy.policyname = 'product_search_tag_published_only_guard'
                  AND policy.permissive = 'RESTRICTIVE'
                  AND policy.cmd = 'SELECT'
                  AND policy.roles = ARRAY['anon', 'authenticated']::name[]
            )
        ),
        (
            'every policy is limited to published products',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_policies AS policy
                WHERE policy.schemaname = 'public'
                  AND policy.tablename = 'product_search_tag'
                  AND policy.qual !~ 'published'
            )
        ),
        (
            'only the three known kinds and sane confidences can be stored',
            (
                SELECT pg_catalog.count(*)
                FROM pg_catalog.pg_constraint AS table_constraint
                WHERE table_constraint.conrelid =
                      pg_catalog.to_regclass('public.product_search_tag')
                  AND table_constraint.contype = 'c'
            ) = 5
        ),
        (
            'no stored tag claims a kind or a confidence the API cannot use',
            NOT EXISTS (
                SELECT 1
                FROM public.product_search_tag AS tag
                WHERE tag.tag_kind NOT IN ('style', 'room_type', 'feel')
                   OR tag.confidence <= 0
                   OR tag.confidence > 1
                   OR tag.source <> 'ai_inferred'
            )
        ),
        (
            'every tag belongs to a product that still exists',
            NOT EXISTS (
                SELECT 1
                FROM public.product_search_tag AS tag
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM public.product AS tagged_product
                    WHERE tagged_product.id = tag.product_id
                )
            )
        )
) AS checks(check_name, passed);
