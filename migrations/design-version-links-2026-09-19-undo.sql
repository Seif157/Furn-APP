/*
Undo design-version-links-2026-09-19.sql: back to the 3.2D state, where the
app cannot attach design versions. Links already created stay.
Exercised on the replica by scripts/replica_design_links_test.py.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';

DROP POLICY IF EXISTS furnishing_design_link_insert_own
ON public.furnishing_request_design_version;
REVOKE INSERT (furnishing_request_id, design_version_id)
ON TABLE public.furnishing_request_design_version
FROM authenticated;
DROP FUNCTION IF EXISTS public.can_attach_design_version(uuid, uuid);

COMMIT;
