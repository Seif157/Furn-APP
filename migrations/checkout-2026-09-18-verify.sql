-- READ ONLY. Checkout verification: every row must show passed = true.
SELECT check_name, passed
FROM (
    VALUES
        (
            'place_order exists, SECURITY DEFINER, owned by postgres',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc AS p
                WHERE p.oid = pg_catalog.to_regprocedure('public.place_order(uuid)')
                  AND p.prosecdef
                  AND pg_catalog.pg_get_userbyid(p.proowner) = 'postgres'
            )
        ),
        (
            'place_order has an empty search_path',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc AS p
                WHERE p.oid = pg_catalog.to_regprocedure('public.place_order(uuid)')
                  AND p.proconfig IN (
                      ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[]
                  )
            )
        ),
        (
            'signed-in users may call place_order',
            pg_catalog.has_function_privilege(
                'authenticated', 'public.place_order(uuid)', 'EXECUTE'
            )
        ),
        (
            'anonymous visitors may not call place_order',
            NOT pg_catalog.has_function_privilege(
                'anon', 'public.place_order(uuid)', 'EXECUTE'
            )
        ),
        (
            'stock-return trigger is on purchase_order',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_trigger AS t
                WHERE t.tgrelid = 'public.purchase_order'::regclass
                  AND t.tgname = 'settle_stock_reservation'
                  AND NOT t.tgisinternal
                  AND t.tgenabled = 'O'
            )
        ),
        (
            'reservations are private to the database',
            NOT pg_catalog.has_schema_privilege('anon', 'checkout_private', 'USAGE')
            AND NOT pg_catalog.has_schema_privilege(
                'authenticated', 'checkout_private', 'USAGE'
            )
        ),
        (
            'no client role can read reservations',
            NOT pg_catalog.has_table_privilege(
                'authenticated', 'checkout_private.stock_reservation', 'SELECT'
            )
            AND NOT pg_catalog.has_table_privilege(
                'anon', 'checkout_private.stock_reservation', 'SELECT'
            )
        ),
        (
            'customers can no longer insert orders directly (3.2D)',
            NOT pg_catalog.has_table_privilege(
                'authenticated', 'public.purchase_order', 'INSERT'
            )
        )
) AS checks(check_name, passed);
