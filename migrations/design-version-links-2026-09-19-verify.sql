-- READ ONLY. Design-link verification: every row must show passed = true.
SELECT check_name, passed
FROM (
    VALUES
        (
            'ownership helper is SECURITY DEFINER with an empty search_path',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc AS p
                WHERE p.oid = pg_catalog.to_regprocedure(
                          'public.can_attach_design_version(uuid, uuid)')
                  AND p.prosecdef
                  AND p.proconfig IN (
                      ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[]
                  )
            )
        ),
        (
            'anonymous visitors cannot call the helper',
            NOT pg_catalog.has_function_privilege(
                'anon', 'public.can_attach_design_version(uuid, uuid)', 'EXECUTE')
        ),
        (
            'insert policy exists for signed-in users only',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_policies AS policy
                WHERE policy.schemaname = 'public'
                  AND policy.tablename = 'furnishing_request_design_version'
                  AND policy.policyname = 'furnishing_design_link_insert_own'
                  AND policy.cmd = 'INSERT'
                  AND policy.roles = ARRAY['authenticated']::name[]
            )
        ),
        (
            'signed-in users may insert only the two link columns',
            pg_catalog.has_column_privilege('authenticated',
                'public.furnishing_request_design_version', 'furnishing_request_id', 'INSERT')
            AND pg_catalog.has_column_privilege('authenticated',
                'public.furnishing_request_design_version', 'design_version_id', 'INSERT')
            AND NOT pg_catalog.has_table_privilege('authenticated',
                'public.furnishing_request_design_version', 'INSERT')
        ),
        (
            'links are never updated by clients',
            NOT pg_catalog.has_table_privilege('authenticated',
                'public.furnishing_request_design_version', 'UPDATE')
            AND NOT pg_catalog.has_column_privilege('authenticated',
                'public.furnishing_request_design_version', 'design_version_id', 'UPDATE')
        ),
        (
            'the 3.2D delete rule is still in place',
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_policies AS policy
                WHERE policy.schemaname = 'public'
                  AND policy.policyname =
                      'phase32d_furnishing_request_design_version_delete_own'
            )
        )
) AS checks(check_name, passed);
