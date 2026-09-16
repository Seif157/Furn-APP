/*
Remove the Phase 5 fake catalogue seed -- FAKE-DATA TESTING BRANCH ONLY.

Deletes only rows whose product carries a SEED- SKU, children first.
Rendered by tests/seed_catalogue.py; do not hand-edit.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

DELETE FROM public.product_image
WHERE product_id IN (SELECT id FROM public.product WHERE sku LIKE 'SEED-%');

DELETE FROM public.product_color
WHERE product_id IN (SELECT id FROM public.product WHERE sku LIKE 'SEED-%');

DELETE FROM public.product
WHERE sku LIKE 'SEED-%';

COMMIT;
