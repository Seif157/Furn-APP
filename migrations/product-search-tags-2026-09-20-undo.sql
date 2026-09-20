/*
Undo the product_search_tag migration.

Dropping the table drops its policies and every inferred tag with it. Nothing
else depends on it: the API treats a missing tag table exactly as it treats an
empty one, so search keeps working and only loses the fuzzy ranking signal.

Safe to run more than once.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';
SET LOCAL search_path = pg_catalog;

DROP TABLE IF EXISTS public.product_search_tag;

DO $search_tags_undo_check$
BEGIN
    IF pg_catalog.to_regclass('public.product_search_tag') IS NOT NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'Search tags undo did not remove the table';
    END IF;
END
$search_tags_undo_check$;

COMMIT;
