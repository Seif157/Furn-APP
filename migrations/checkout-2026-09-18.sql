/*
Checkout: place_order(address_id) and stock returned on cancellation.

Apply only after the Phase 3.2D migration. 3.2D makes orders server-created:
clients lose INSERT on purchase_order, so this function is the way an order is
placed. Decisions recorded 2026-09-18 by the owner: delivery is free for now
(delivery_fee = 0), payment is cash on delivery (no upfront amount), and
placing an order reserves stock, which comes back if the order is cancelled.

One transaction. It checks its prerequisites before changing anything and
verifies the result before committing; any failure rolls everything back.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

DO $checkout_preflight$
BEGIN
    IF pg_catalog.current_setting('server_version_num')::pg_catalog.int4 < 150000 THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout requires PostgreSQL 15 or newer';
    END IF;

    -- Phase 3.2D must be applied first: it removes client INSERT on orders and
    -- defines the cancellation function whose effect the trigger reverses.
    IF pg_catalog.to_regprocedure(
           'public.cancel_purchase_order(pg_catalog.uuid)'
       ) IS NULL
       OR pg_catalog.to_regprocedure(
           'public.advance_purchase_order(pg_catalog.uuid, public.order_state)'
       ) IS NULL
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout requires the applied Phase 3.2D migration';
    END IF;

    IF pg_catalog.to_regprocedure('public.place_order(pg_catalog.uuid)') IS NOT NULL
       OR pg_catalog.to_regnamespace('checkout_private') IS NOT NULL
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout is already applied';
    END IF;

    -- Every column the function reads or writes, with the type it relies on.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.customer_profile'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.customer_profile'::pg_catalog.regclass, 'user_id'::name, 'uuid'::text),
                ('public.address'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.address'::pg_catalog.regclass, 'customer_profile_id'::name, 'uuid'::text),
                ('public.address'::pg_catalog.regclass, 'recipient_name'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'contact_phone'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'address_line_1'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'address_line_2'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'city'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'country'::name, 'text'::text),
                ('public.address'::pg_catalog.regclass, 'latitude'::name, 'numeric'::text),
                ('public.address'::pg_catalog.regclass, 'longitude'::name, 'numeric'::text),
                ('public.cart'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.cart'::pg_catalog.regclass, 'customer_profile_id'::name, 'uuid'::text),
                ('public.cart_line'::pg_catalog.regclass, 'cart_id'::name, 'uuid'::text),
                ('public.cart_line'::pg_catalog.regclass, 'product_color_id'::name, 'uuid'::text),
                ('public.cart_line'::pg_catalog.regclass, 'quantity'::name, 'int4'::text),
                ('public.product_color'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.product_color'::pg_catalog.regclass, 'product_id'::name, 'uuid'::text),
                ('public.product_color'::pg_catalog.regclass, 'color_value'::name, 'text'::text),
                ('public.product_color'::pg_catalog.regclass, 'stock_quantity'::name, 'int4'::text),
                ('public.product'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.product'::pg_catalog.regclass, 'marketplace_party_id'::name, 'uuid'::text),
                ('public.product'::pg_catalog.regclass, 'category_id'::name, 'uuid'::text),
                ('public.product'::pg_catalog.regclass, 'name'::name, 'text'::text),
                ('public.product'::pg_catalog.regclass, 'price'::name, 'numeric'::text),
                ('public.product'::pg_catalog.regclass, 'discount_price'::name, 'numeric'::text),
                ('public.product'::pg_catalog.regclass, 'lifecycle_state'::name, 'product_state'::text),
                ('public.category'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.category'::pg_catalog.regclass, 'is_active'::name, 'bool'::text),
                ('public.marketplace_party'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.marketplace_party'::pg_catalog.regclass, 'approval_state'::name, 'party_approval_state'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'id'::name, 'uuid'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'customer_profile_id'::name, 'uuid'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'marketplace_party_id'::name, 'uuid'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'address_id'::name, 'uuid'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'origin'::name, 'order_origin'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'lifecycle_state'::name, 'order_state'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'delivery_fee'::name, 'numeric'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_recipient_name'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_contact_phone'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_address_line_1'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_address_line_2'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_city'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_country'::name, 'text'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_latitude'::name, 'numeric'::text),
                ('public.purchase_order'::pg_catalog.regclass, 'ship_longitude'::name, 'numeric'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'order_id'::name, 'uuid'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'line_kind'::name, 'line_kind'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'product_id'::name, 'uuid'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'product_color_id'::name, 'uuid'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'item_name'::name, 'text'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'specification'::name, 'text'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'unit_price'::name, 'numeric'::text),
                ('public.order_line_item'::pg_catalog.regclass, 'quantity'::name, 'int4'::text)
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
        RAISE EXCEPTION USING MESSAGE = 'Checkout column drift';
    END IF;

    -- The enum labels the function writes or compares against.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('order_origin'::name, 'stocked'::name),
                ('order_state'::name, 'pending'::name),
                ('order_state'::name, 'cancelled'::name),
                ('order_state'::name, 'delivered'::name),
                ('line_kind'::name, 'catalog'::name),
                ('product_state'::name, 'published'::name),
                ('party_approval_state'::name, 'approved'::name)
        ) AS required(type_name, label)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_enum AS enum_value
            JOIN pg_catalog.pg_type AS enum_type
                ON enum_type.oid = enum_value.enumtypid
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = enum_type.typnamespace
            WHERE namespace.nspname = 'public'
              AND enum_type.typname = required.type_name
              AND enum_value.enumlabel = required.label
        )
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout enum drift';
    END IF;

    -- line_total must be computed by the database, never written.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = 'public.order_line_item'::pg_catalog.regclass
          AND attribute.attname = 'line_total'
          AND attribute.attgenerated = 's'::pg_catalog."char"
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout expects a generated line_total';
    END IF;
END
$checkout_preflight$;

-- What each order reserved, so a cancellation returns exactly that, once.
-- A private schema: not exposed through the API, and outside the public-table
-- inventory the security packages verify.
CREATE SCHEMA checkout_private;
REVOKE ALL ON SCHEMA checkout_private FROM PUBLIC;

CREATE TABLE checkout_private.stock_reservation (
    order_id pg_catalog.uuid NOT NULL
        REFERENCES public.purchase_order (id) ON DELETE CASCADE,
    product_color_id pg_catalog.uuid NOT NULL
        REFERENCES public.product_color (id) ON DELETE CASCADE,
    quantity pg_catalog.int4 NOT NULL CHECK (quantity > 0),
    reserved_at pg_catalog.timestamptz NOT NULL DEFAULT pg_catalog.now(),
    PRIMARY KEY (order_id, product_color_id)
);
ALTER TABLE checkout_private.stock_reservation ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE checkout_private.stock_reservation
FROM PUBLIC, anon, authenticated, service_role;

/*
 * Place one order per seller from the caller's cart.
 *
 * Identity comes only from auth.uid(). Prices, names and stock come only from
 * the catalogue, read under a row lock, never from the caller. Every line is
 * rechecked: published product, approved seller, active category, enough stock
 * in the chosen colour. Any failure raises and nothing is written.
 *
 * Errors (the message is the code): customer_profile_required,
 * address_not_found, cart_empty, product_unavailable, insufficient_stock.
 */
CREATE FUNCTION public.place_order(address_id pg_catalog.uuid)
RETURNS pg_catalog.jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    buyer_profile_id pg_catalog.uuid;
    buyer_cart_id pg_catalog.uuid;
    shipping public.address%ROWTYPE;
    failing_color_id pg_catalog.uuid;
    seller_id pg_catalog.uuid;
    new_order_id pg_catalog.uuid;
    placed pg_catalog.jsonb := '[]'::pg_catalog.jsonb;
BEGIN
    SELECT customer.id
    INTO buyer_profile_id
    FROM public.customer_profile AS customer
    WHERE customer.user_id = auth.uid();

    IF buyer_profile_id IS NULL THEN
        RAISE EXCEPTION USING MESSAGE = 'customer_profile_required';
    END IF;

    SELECT *
    INTO shipping
    FROM public.address AS delivery
    WHERE delivery.id = place_order.address_id
      AND delivery.customer_profile_id = buyer_profile_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING MESSAGE = 'address_not_found';
    END IF;

    SELECT buyer_cart.id
    INTO buyer_cart_id
    FROM public.cart AS buyer_cart
    WHERE buyer_cart.customer_profile_id = buyer_profile_id;

    IF buyer_cart_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.cart_line AS line WHERE line.cart_id = buyer_cart_id
    ) THEN
        RAISE EXCEPTION USING MESSAGE = 'cart_empty';
    END IF;

    -- Lock every colour the cart uses, in a fixed order so two checkouts
    -- cannot deadlock, before any stock is read for the checks below.
    PERFORM 1
    FROM public.product_color AS colour
    WHERE colour.id IN (
        SELECT line.product_color_id
        FROM public.cart_line AS line
        WHERE line.cart_id = buyer_cart_id
    )
    ORDER BY colour.id
    FOR UPDATE;

    SELECT line.product_color_id
    INTO failing_color_id
    FROM public.cart_line AS line
    JOIN public.product_color AS colour ON colour.id = line.product_color_id
    JOIN public.product AS item ON item.id = colour.product_id
    JOIN public.marketplace_party AS seller ON seller.id = item.marketplace_party_id
    JOIN public.category AS item_category ON item_category.id = item.category_id
    WHERE line.cart_id = buyer_cart_id
      AND NOT (
          item.lifecycle_state = 'published'
          AND seller.approval_state = 'approved'
          AND item_category.is_active
      )
    LIMIT 1;

    IF failing_color_id IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = 'product_unavailable',
            DETAIL = failing_color_id::text;
    END IF;

    SELECT line.product_color_id
    INTO failing_color_id
    FROM public.cart_line AS line
    JOIN public.product_color AS colour ON colour.id = line.product_color_id
    WHERE line.cart_id = buyer_cart_id
      AND colour.stock_quantity < line.quantity
    LIMIT 1;

    IF failing_color_id IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = 'insufficient_stock',
            DETAIL = failing_color_id::text;
    END IF;

    FOR seller_id IN
        SELECT DISTINCT item.marketplace_party_id
        FROM public.cart_line AS line
        JOIN public.product_color AS colour ON colour.id = line.product_color_id
        JOIN public.product AS item ON item.id = colour.product_id
        WHERE line.cart_id = buyer_cart_id
        ORDER BY item.marketplace_party_id
    LOOP
        INSERT INTO public.purchase_order (
            customer_profile_id,
            marketplace_party_id,
            address_id,
            origin,
            delivery_fee,
            ship_recipient_name,
            ship_contact_phone,
            ship_address_line_1,
            ship_address_line_2,
            ship_city,
            ship_country,
            ship_latitude,
            ship_longitude
        )
        VALUES (
            buyer_profile_id,
            seller_id,
            shipping.id,
            'stocked',
            0,
            shipping.recipient_name,
            shipping.contact_phone,
            shipping.address_line_1,
            shipping.address_line_2,
            shipping.city,
            shipping.country,
            shipping.latitude,
            shipping.longitude
        )
        RETURNING id INTO new_order_id;

        INSERT INTO public.order_line_item (
            order_id,
            line_kind,
            product_id,
            product_color_id,
            item_name,
            specification,
            unit_price,
            quantity
        )
        SELECT
            new_order_id,
            'catalog',
            item.id,
            colour.id,
            item.name,
            colour.color_value,
            -- What the customer pays, as search and the app show it.
            CASE
                WHEN item.discount_price IS NOT NULL
                     AND item.discount_price < item.price
                THEN item.discount_price
                ELSE item.price
            END,
            line.quantity
        FROM public.cart_line AS line
        JOIN public.product_color AS colour ON colour.id = line.product_color_id
        JOIN public.product AS item ON item.id = colour.product_id
        WHERE line.cart_id = buyer_cart_id
          AND item.marketplace_party_id = seller_id;

        INSERT INTO checkout_private.stock_reservation (
            order_id, product_color_id, quantity
        )
        SELECT new_order_id, line.product_color_id, line.quantity
        FROM public.cart_line AS line
        JOIN public.product_color AS colour ON colour.id = line.product_color_id
        JOIN public.product AS item ON item.id = colour.product_id
        WHERE line.cart_id = buyer_cart_id
          AND item.marketplace_party_id = seller_id;

        placed := placed || pg_catalog.jsonb_build_object(
            'order_id', new_order_id,
            'marketplace_party_id', seller_id
        );
    END LOOP;

    UPDATE public.product_color AS colour
    SET stock_quantity = colour.stock_quantity - line.quantity
    FROM public.cart_line AS line
    WHERE line.cart_id = buyer_cart_id
      AND line.product_color_id = colour.id;

    DELETE FROM public.cart_line AS line WHERE line.cart_id = buyer_cart_id;

    RETURN placed;
END
$function$;

ALTER FUNCTION public.place_order(pg_catalog.uuid) OWNER TO postgres;
REVOKE ALL PRIVILEGES ON FUNCTION public.place_order(pg_catalog.uuid)
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.place_order(pg_catalog.uuid)
TO authenticated, service_role;

/*
 * Return reserved stock when an order is cancelled, by any route: the
 * customer's cancel_purchase_order, an administrator, or a future seller path.
 * The reservation rows are deleted as they are returned, so a second
 * cancellation returns nothing. A delivered order keeps its stock consumed and
 * its reservation rows are dropped.
 */
CREATE FUNCTION checkout_private.settle_stock_reservation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    IF NEW.lifecycle_state::text = 'cancelled' THEN
        UPDATE public.product_color AS colour
        SET stock_quantity = colour.stock_quantity + reservation.quantity
        FROM checkout_private.stock_reservation AS reservation
        WHERE reservation.order_id = NEW.id
          AND reservation.product_color_id = colour.id;
    END IF;

    DELETE FROM checkout_private.stock_reservation AS reservation
    WHERE reservation.order_id = NEW.id;

    RETURN NULL;
END
$function$;

ALTER FUNCTION checkout_private.settle_stock_reservation() OWNER TO postgres;
REVOKE ALL PRIVILEGES ON FUNCTION checkout_private.settle_stock_reservation()
FROM PUBLIC, anon, authenticated, service_role;

CREATE TRIGGER settle_stock_reservation
AFTER UPDATE OF lifecycle_state ON public.purchase_order
FOR EACH ROW
WHEN (
    NEW.lifecycle_state IS DISTINCT FROM OLD.lifecycle_state
    AND NEW.lifecycle_state::text IN ('cancelled', 'delivered')
)
EXECUTE FUNCTION checkout_private.settle_stock_reservation();

DO $checkout_postflight$
DECLARE
    place_oid oid := 'public.place_order(pg_catalog.uuid)'::pg_catalog.regprocedure;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS function_metadata
        WHERE function_metadata.oid = place_oid
          AND function_metadata.prosecdef
          AND function_metadata.provolatile = 'v'::pg_catalog."char"
          AND pg_catalog.pg_get_userbyid(function_metadata.proowner) = 'postgres'
          AND function_metadata.proconfig IN
              (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
    )
       OR pg_catalog.has_function_privilege('anon', place_oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('authenticated', place_oid, 'EXECUTE')
       OR pg_catalog.has_table_privilege(
           'authenticated', 'checkout_private.stock_reservation', 'SELECT'
       )
       OR pg_catalog.has_schema_privilege('anon', 'checkout_private', 'USAGE')
       OR pg_catalog.has_schema_privilege('authenticated', 'checkout_private', 'USAGE')
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_trigger AS trigger_row
           WHERE trigger_row.tgrelid = 'public.purchase_order'::pg_catalog.regclass
             AND trigger_row.tgname = 'settle_stock_reservation'
             AND NOT trigger_row.tgisinternal
       )
    THEN
        RAISE EXCEPTION USING MESSAGE = 'Checkout postflight mismatch';
    END IF;
END
$checkout_postflight$;

COMMIT;
