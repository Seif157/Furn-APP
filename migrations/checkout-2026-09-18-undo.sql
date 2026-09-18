/*
Undo checkout-2026-09-18.sql. Run only if checkout must be removed.

Removes place_order, the stock-return trigger and the private reservation
records. Orders already placed stay, with the stock they reserved still taken:
after this, cancelling one of them no longer returns its stock. Run it before
any real order exists if the choice is open.

Exercised on the replica by scripts/replica_checkout_test.py (apply, undo,
apply again).
*/

BEGIN;

SET LOCAL lock_timeout = '5s';

DROP TRIGGER IF EXISTS settle_stock_reservation ON public.purchase_order;
DROP FUNCTION IF EXISTS public.place_order(pg_catalog.uuid);
DROP SCHEMA IF EXISTS checkout_private CASCADE;

COMMIT;
