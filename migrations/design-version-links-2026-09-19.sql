/*
Let customers attach their own design versions to their own furnishing
requests again.

Apply only after Phase 3.2D. 3.2D removed INSERT on
furnishing_request_design_version from clients on the assumption that the
server creates these links; its decision record says to switch to
customer-creates if the app inserts them, and the owner confirmed on
2026-09-19 that the app does.

The rule: a signed-in customer may insert a link only when the furnishing
request is theirs and still draft or open, and the design version belongs to a
design they created. Only the two link columns are writable; links are never
updated. Deleting keeps 3.2D's rule (own request, draft or open).

Ownership is checked by one SECURITY DEFINER helper rather than subqueries in
the policy, so the check does not depend on what the caller may read from
design and design_version under their own row-level security.

One transaction; any failed check rolls everything back.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $design_links_preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = 'furnishing_request_design_version'
          AND policy.policyname = 'phase32d_furnishing_request_design_version_delete_own'
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Design links require the applied Phase 3.2D migration';
    END IF;

    IF pg_catalog.to_regprocedure(
           'public.can_attach_design_version(pg_catalog.uuid, pg_catalog.uuid)'
       ) IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_policies AS policy
           WHERE policy.schemaname = 'public'
             AND policy.policyname = 'furnishing_design_link_insert_own'
       )
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Design links are already applied';
    END IF;

    -- The 3.2D state: signed-in users cannot insert or update links at all.
    IF pg_catalog.has_table_privilege(
           'authenticated', 'public.furnishing_request_design_version', 'INSERT'
       )
       OR pg_catalog.has_table_privilege(
           'authenticated', 'public.furnishing_request_design_version', 'UPDATE'
       )
       OR pg_catalog.has_column_privilege(
           'authenticated', 'public.furnishing_request_design_version',
           'furnishing_request_id', 'INSERT'
       )
       OR pg_catalog.has_column_privilege(
           'authenticated', 'public.furnishing_request_design_version',
           'design_version_id', 'INSERT'
       )
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Design links privilege baseline drift';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.furnishing_request_design_version'::pg_catalog.regclass, 'furnishing_request_id'::name, 'uuid'::name),
                ('public.furnishing_request_design_version'::pg_catalog.regclass, 'design_version_id'::name, 'uuid'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'id'::name, 'uuid'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'customer_profile_id'::name, 'uuid'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'lifecycle_state'::name, 'furnishing_request_state'::name),
                ('public.customer_profile'::pg_catalog.regclass, 'id'::name, 'uuid'::name),
                ('public.customer_profile'::pg_catalog.regclass, 'user_id'::name, 'uuid'::name),
                ('public.design_version'::pg_catalog.regclass, 'id'::name, 'uuid'::name),
                ('public.design_version'::pg_catalog.regclass, 'design_id'::name, 'uuid'::name),
                ('public.design'::pg_catalog.regclass, 'id'::name, 'uuid'::name),
                ('public.design'::pg_catalog.regclass, 'originating_user_id'::name, 'uuid'::name)
        ) AS required(table_oid, column_name, type_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute AS attribute
            JOIN pg_catalog.pg_type AS column_type
                ON column_type.oid = attribute.atttypid
            WHERE attribute.attrelid = required.table_oid
              AND attribute.attname = required.column_name
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND column_type.typname = required.type_name
        )
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Design links column drift';
    END IF;
END
$design_links_preflight$;

CREATE FUNCTION public.can_attach_design_version(
    request_id pg_catalog.uuid,
    version_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.furnishing_request AS parent_request
        JOIN public.customer_profile AS customer
            ON customer.id = parent_request.customer_profile_id
        WHERE parent_request.id = request_id
          AND customer.user_id = auth.uid()
          AND parent_request.lifecycle_state::text IN ('draft', 'open')
    )
    AND EXISTS (
        SELECT 1
        FROM public.design_version AS attached_version
        JOIN public.design AS owned_design
            ON owned_design.id = attached_version.design_id
        WHERE attached_version.id = version_id
          AND owned_design.originating_user_id = auth.uid()
    )
$function$;

ALTER FUNCTION public.can_attach_design_version(pg_catalog.uuid, pg_catalog.uuid)
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.can_attach_design_version(pg_catalog.uuid, pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.can_attach_design_version(pg_catalog.uuid, pg_catalog.uuid)
TO authenticated, service_role;

GRANT INSERT (furnishing_request_id, design_version_id)
ON TABLE public.furnishing_request_design_version
TO authenticated;

CREATE POLICY furnishing_design_link_insert_own
ON public.furnishing_request_design_version
FOR INSERT
TO authenticated
WITH CHECK (
    public.can_attach_design_version(furnishing_request_id, design_version_id)
);

DO $design_links_postflight$
DECLARE
    helper_oid oid := 'public.can_attach_design_version(pg_catalog.uuid, pg_catalog.uuid)'::pg_catalog.regprocedure;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_metadata
        WHERE function_metadata.oid = helper_oid
          AND function_metadata.prosecdef
          AND pg_catalog.pg_get_userbyid(function_metadata.proowner) = 'postgres'
          AND function_metadata.proconfig IN
              (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
    )
       OR pg_catalog.has_function_privilege('anon', helper_oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('authenticated', helper_oid, 'EXECUTE')
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_policies AS policy
           WHERE policy.schemaname = 'public'
             AND policy.tablename = 'furnishing_request_design_version'
             AND policy.policyname = 'furnishing_design_link_insert_own'
             AND policy.cmd = 'INSERT'
             AND policy.permissive = 'PERMISSIVE'
             AND policy.roles = ARRAY['authenticated']::name[]
       )
       OR pg_catalog.has_table_privilege(
           'authenticated', 'public.furnishing_request_design_version', 'INSERT'
       )
       OR pg_catalog.has_table_privilege(
           'authenticated', 'public.furnishing_request_design_version', 'UPDATE'
       )
       OR NOT pg_catalog.has_column_privilege(
           'authenticated', 'public.furnishing_request_design_version',
           'furnishing_request_id', 'INSERT'
       )
       OR NOT pg_catalog.has_column_privilege(
           'authenticated', 'public.furnishing_request_design_version',
           'design_version_id', 'INSERT'
       )
       OR pg_catalog.has_column_privilege(
           'anon', 'public.furnishing_request_design_version',
           'furnishing_request_id', 'INSERT'
       )
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Design links postflight mismatch';
    END IF;
END
$design_links_postflight$;

COMMIT;
