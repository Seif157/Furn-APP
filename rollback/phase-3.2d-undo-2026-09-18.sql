-- Phase 3.2D UNDO, generated 2026-09-18 20:36:52.251209+00 from the live state before the migration.
-- Run only if 3.2D was applied and must be reversed.
BEGIN;
SET LOCAL lock_timeout = '5s';

-- snapshot check: 3.2D not applied

DO $drop_policies$
DECLARE target record;
BEGIN
    FOR target IN
        SELECT policyname, tablename FROM pg_catalog.pg_policies
        WHERE schemaname = 'public'
          AND tablename = ANY (ARRAY['address', 'cart', 'cart_line', 'custom_offering', 'design_product_reference', 'furnishing_request_design_version', 'marketplace_party', 'offer_line_item', 'party_capability', 'purchase_order', 'review', 'saved_space', 'service_request'])
    LOOP
        EXECUTE pg_catalog.format(
            'DROP POLICY %I ON public.%I', target.policyname, target.tablename
        );
    END LOOP;
END
$drop_policies$;

DROP FUNCTION IF EXISTS public.cancel_service_request(pg_catalog.uuid);
DROP FUNCTION IF EXISTS public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric);
DROP FUNCTION IF EXISTS public.start_service_request(pg_catalog.uuid);
DROP FUNCTION IF EXISTS public.complete_service_request(pg_catalog.uuid);
DROP FUNCTION IF EXISTS public.advance_purchase_order(pg_catalog.uuid, public.order_state);
DROP FUNCTION IF EXISTS public.cancel_purchase_order(pg_catalog.uuid);

REVOKE ALL ON TABLE public.address FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.address TO authenticated;
GRANT INSERT ON TABLE public.address TO authenticated;
GRANT SELECT ON TABLE public.address TO authenticated;
GRANT UPDATE ON TABLE public.address TO authenticated;
GRANT DELETE ON TABLE public.address TO service_role;
GRANT INSERT ON TABLE public.address TO service_role;
GRANT MAINTAIN ON TABLE public.address TO service_role;
GRANT REFERENCES ON TABLE public.address TO service_role;
GRANT SELECT ON TABLE public.address TO service_role;
GRANT TRIGGER ON TABLE public.address TO service_role;
GRANT TRUNCATE ON TABLE public.address TO service_role;
GRANT UPDATE ON TABLE public.address TO service_role;

REVOKE ALL ON TABLE public.cart FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.cart TO authenticated;
GRANT INSERT ON TABLE public.cart TO authenticated;
GRANT SELECT ON TABLE public.cart TO authenticated;
GRANT UPDATE ON TABLE public.cart TO authenticated;
GRANT DELETE ON TABLE public.cart TO service_role;
GRANT INSERT ON TABLE public.cart TO service_role;
GRANT MAINTAIN ON TABLE public.cart TO service_role;
GRANT REFERENCES ON TABLE public.cart TO service_role;
GRANT SELECT ON TABLE public.cart TO service_role;
GRANT TRIGGER ON TABLE public.cart TO service_role;
GRANT TRUNCATE ON TABLE public.cart TO service_role;
GRANT UPDATE ON TABLE public.cart TO service_role;

REVOKE ALL ON TABLE public.cart_line FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.cart_line TO authenticated;
GRANT INSERT ON TABLE public.cart_line TO authenticated;
GRANT SELECT ON TABLE public.cart_line TO authenticated;
GRANT UPDATE ON TABLE public.cart_line TO authenticated;
GRANT DELETE ON TABLE public.cart_line TO service_role;
GRANT INSERT ON TABLE public.cart_line TO service_role;
GRANT MAINTAIN ON TABLE public.cart_line TO service_role;
GRANT REFERENCES ON TABLE public.cart_line TO service_role;
GRANT SELECT ON TABLE public.cart_line TO service_role;
GRANT TRIGGER ON TABLE public.cart_line TO service_role;
GRANT TRUNCATE ON TABLE public.cart_line TO service_role;
GRANT UPDATE ON TABLE public.cart_line TO service_role;

REVOKE ALL ON TABLE public.custom_offering FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.custom_offering TO anon;
GRANT DELETE ON TABLE public.custom_offering TO authenticated;
GRANT INSERT ON TABLE public.custom_offering TO authenticated;
GRANT SELECT ON TABLE public.custom_offering TO authenticated;
GRANT UPDATE ON TABLE public.custom_offering TO authenticated;
GRANT DELETE ON TABLE public.custom_offering TO service_role;
GRANT INSERT ON TABLE public.custom_offering TO service_role;
GRANT MAINTAIN ON TABLE public.custom_offering TO service_role;
GRANT REFERENCES ON TABLE public.custom_offering TO service_role;
GRANT SELECT ON TABLE public.custom_offering TO service_role;
GRANT TRIGGER ON TABLE public.custom_offering TO service_role;
GRANT TRUNCATE ON TABLE public.custom_offering TO service_role;
GRANT UPDATE ON TABLE public.custom_offering TO service_role;

REVOKE ALL ON TABLE public.design_product_reference FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.design_product_reference TO authenticated;
GRANT INSERT ON TABLE public.design_product_reference TO authenticated;
GRANT SELECT ON TABLE public.design_product_reference TO authenticated;
GRANT UPDATE ON TABLE public.design_product_reference TO authenticated;
GRANT DELETE ON TABLE public.design_product_reference TO service_role;
GRANT INSERT ON TABLE public.design_product_reference TO service_role;
GRANT MAINTAIN ON TABLE public.design_product_reference TO service_role;
GRANT REFERENCES ON TABLE public.design_product_reference TO service_role;
GRANT SELECT ON TABLE public.design_product_reference TO service_role;
GRANT TRIGGER ON TABLE public.design_product_reference TO service_role;
GRANT TRUNCATE ON TABLE public.design_product_reference TO service_role;
GRANT UPDATE ON TABLE public.design_product_reference TO service_role;

REVOKE ALL ON TABLE public.furnishing_request_design_version FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.furnishing_request_design_version TO authenticated;
GRANT INSERT ON TABLE public.furnishing_request_design_version TO authenticated;
GRANT SELECT ON TABLE public.furnishing_request_design_version TO authenticated;
GRANT UPDATE ON TABLE public.furnishing_request_design_version TO authenticated;
GRANT DELETE ON TABLE public.furnishing_request_design_version TO service_role;
GRANT INSERT ON TABLE public.furnishing_request_design_version TO service_role;
GRANT MAINTAIN ON TABLE public.furnishing_request_design_version TO service_role;
GRANT REFERENCES ON TABLE public.furnishing_request_design_version TO service_role;
GRANT SELECT ON TABLE public.furnishing_request_design_version TO service_role;
GRANT TRIGGER ON TABLE public.furnishing_request_design_version TO service_role;
GRANT TRUNCATE ON TABLE public.furnishing_request_design_version TO service_role;
GRANT UPDATE ON TABLE public.furnishing_request_design_version TO service_role;

REVOKE ALL ON TABLE public.marketplace_party FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.marketplace_party TO anon;
GRANT DELETE ON TABLE public.marketplace_party TO authenticated;
GRANT SELECT ON TABLE public.marketplace_party TO authenticated;
GRANT DELETE ON TABLE public.marketplace_party TO service_role;
GRANT INSERT ON TABLE public.marketplace_party TO service_role;
GRANT MAINTAIN ON TABLE public.marketplace_party TO service_role;
GRANT REFERENCES ON TABLE public.marketplace_party TO service_role;
GRANT SELECT ON TABLE public.marketplace_party TO service_role;
GRANT TRIGGER ON TABLE public.marketplace_party TO service_role;
GRANT TRUNCATE ON TABLE public.marketplace_party TO service_role;
GRANT UPDATE ON TABLE public.marketplace_party TO service_role;
GRANT INSERT (user_id) ON TABLE public.marketplace_party TO authenticated;
GRANT INSERT (business_name) ON TABLE public.marketplace_party TO authenticated;
GRANT UPDATE (business_name) ON TABLE public.marketplace_party TO authenticated;
GRANT INSERT (business_description) ON TABLE public.marketplace_party TO authenticated;
GRANT UPDATE (business_description) ON TABLE public.marketplace_party TO authenticated;
GRANT INSERT (logo_url) ON TABLE public.marketplace_party TO authenticated;
GRANT UPDATE (logo_url) ON TABLE public.marketplace_party TO authenticated;
GRANT INSERT (coverage_area) ON TABLE public.marketplace_party TO authenticated;
GRANT UPDATE (coverage_area) ON TABLE public.marketplace_party TO authenticated;

REVOKE ALL ON TABLE public.offer_line_item FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.offer_line_item TO authenticated;
GRANT INSERT ON TABLE public.offer_line_item TO authenticated;
GRANT SELECT ON TABLE public.offer_line_item TO authenticated;
GRANT UPDATE ON TABLE public.offer_line_item TO authenticated;
GRANT DELETE ON TABLE public.offer_line_item TO service_role;
GRANT INSERT ON TABLE public.offer_line_item TO service_role;
GRANT MAINTAIN ON TABLE public.offer_line_item TO service_role;
GRANT REFERENCES ON TABLE public.offer_line_item TO service_role;
GRANT SELECT ON TABLE public.offer_line_item TO service_role;
GRANT TRIGGER ON TABLE public.offer_line_item TO service_role;
GRANT TRUNCATE ON TABLE public.offer_line_item TO service_role;
GRANT UPDATE ON TABLE public.offer_line_item TO service_role;

REVOKE ALL ON TABLE public.party_capability FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.party_capability TO anon;
GRANT DELETE ON TABLE public.party_capability TO authenticated;
GRANT INSERT ON TABLE public.party_capability TO authenticated;
GRANT SELECT ON TABLE public.party_capability TO authenticated;
GRANT UPDATE ON TABLE public.party_capability TO authenticated;
GRANT DELETE ON TABLE public.party_capability TO service_role;
GRANT INSERT ON TABLE public.party_capability TO service_role;
GRANT MAINTAIN ON TABLE public.party_capability TO service_role;
GRANT REFERENCES ON TABLE public.party_capability TO service_role;
GRANT SELECT ON TABLE public.party_capability TO service_role;
GRANT TRIGGER ON TABLE public.party_capability TO service_role;
GRANT TRUNCATE ON TABLE public.party_capability TO service_role;
GRANT UPDATE ON TABLE public.party_capability TO service_role;

REVOKE ALL ON TABLE public.purchase_order FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.purchase_order TO authenticated;
GRANT INSERT ON TABLE public.purchase_order TO authenticated;
GRANT SELECT ON TABLE public.purchase_order TO authenticated;
GRANT DELETE ON TABLE public.purchase_order TO service_role;
GRANT INSERT ON TABLE public.purchase_order TO service_role;
GRANT MAINTAIN ON TABLE public.purchase_order TO service_role;
GRANT REFERENCES ON TABLE public.purchase_order TO service_role;
GRANT SELECT ON TABLE public.purchase_order TO service_role;
GRANT TRIGGER ON TABLE public.purchase_order TO service_role;
GRANT TRUNCATE ON TABLE public.purchase_order TO service_role;
GRANT UPDATE ON TABLE public.purchase_order TO service_role;
GRANT UPDATE (lifecycle_state) ON TABLE public.purchase_order TO authenticated;
GRANT UPDATE (notes) ON TABLE public.purchase_order TO authenticated;

REVOKE ALL ON TABLE public.review FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.review TO authenticated;
GRANT INSERT ON TABLE public.review TO authenticated;
GRANT SELECT ON TABLE public.review TO authenticated;
GRANT UPDATE ON TABLE public.review TO authenticated;
GRANT DELETE ON TABLE public.review TO service_role;
GRANT INSERT ON TABLE public.review TO service_role;
GRANT MAINTAIN ON TABLE public.review TO service_role;
GRANT REFERENCES ON TABLE public.review TO service_role;
GRANT SELECT ON TABLE public.review TO service_role;
GRANT TRIGGER ON TABLE public.review TO service_role;
GRANT TRUNCATE ON TABLE public.review TO service_role;
GRANT UPDATE ON TABLE public.review TO service_role;
GRANT SELECT (id) ON TABLE public.review TO anon;
GRANT SELECT (target_kind) ON TABLE public.review TO anon;
GRANT SELECT (target_product_id) ON TABLE public.review TO anon;
GRANT SELECT (target_marketplace_party_id) ON TABLE public.review TO anon;
GRANT SELECT (rating) ON TABLE public.review TO anon;
GRANT SELECT (comment) ON TABLE public.review TO anon;
GRANT SELECT (created_at) ON TABLE public.review TO anon;

REVOKE ALL ON TABLE public.saved_space FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.saved_space TO authenticated;
GRANT INSERT ON TABLE public.saved_space TO authenticated;
GRANT SELECT ON TABLE public.saved_space TO authenticated;
GRANT UPDATE ON TABLE public.saved_space TO authenticated;
GRANT DELETE ON TABLE public.saved_space TO service_role;
GRANT INSERT ON TABLE public.saved_space TO service_role;
GRANT MAINTAIN ON TABLE public.saved_space TO service_role;
GRANT REFERENCES ON TABLE public.saved_space TO service_role;
GRANT SELECT ON TABLE public.saved_space TO service_role;
GRANT TRIGGER ON TABLE public.saved_space TO service_role;
GRANT TRUNCATE ON TABLE public.saved_space TO service_role;
GRANT UPDATE ON TABLE public.saved_space TO service_role;

REVOKE ALL ON TABLE public.service_request FROM PUBLIC, anon, authenticated, service_role;
GRANT DELETE ON TABLE public.service_request TO authenticated;
GRANT INSERT ON TABLE public.service_request TO authenticated;
GRANT SELECT ON TABLE public.service_request TO authenticated;
GRANT DELETE ON TABLE public.service_request TO service_role;
GRANT INSERT ON TABLE public.service_request TO service_role;
GRANT MAINTAIN ON TABLE public.service_request TO service_role;
GRANT REFERENCES ON TABLE public.service_request TO service_role;
GRANT SELECT ON TABLE public.service_request TO service_role;
GRANT TRIGGER ON TABLE public.service_request TO service_role;
GRANT TRUNCATE ON TABLE public.service_request TO service_role;
GRANT UPDATE ON TABLE public.service_request TO service_role;
GRANT UPDATE (scheduled_date) ON TABLE public.service_request TO authenticated;
GRANT UPDATE (scheduled_time) ON TABLE public.service_request TO authenticated;
GRANT UPDATE (details) ON TABLE public.service_request TO authenticated;
GRANT UPDATE (lifecycle_state) ON TABLE public.service_request TO authenticated;
GRANT UPDATE (completed_at) ON TABLE public.service_request TO authenticated;

CREATE POLICY address_select_own_or_engaged ON public.address AS PERMISSIVE FOR SELECT TO authenticated
    USING (((customer_profile_id = current_customer_profile_id()) OR (EXISTS ( SELECT 1
   FROM service_request sr
  WHERE ((sr.address_id = address.id) AND (sr.marketplace_party_id = current_marketplace_party_id()) AND (sr.lifecycle_state <> 'pending'::service_request_state)))) OR (EXISTS ( SELECT 1
   FROM purchase_order po
  WHERE ((po.address_id = address.id) AND (po.marketplace_party_id = current_marketplace_party_id()))))));
CREATE POLICY address_write_own ON public.address AS PERMISSIVE FOR ALL TO authenticated
    USING ((customer_profile_id = current_customer_profile_id()))
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY cart_all_own ON public.cart AS PERMISSIVE FOR ALL TO authenticated
    USING ((customer_profile_id = current_customer_profile_id()))
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY cart_line_all_own ON public.cart_line AS PERMISSIVE FOR ALL TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM cart c
  WHERE ((c.id = cart_line.cart_id) AND (c.customer_profile_id = current_customer_profile_id())))))
    WITH CHECK ((EXISTS ( SELECT 1
   FROM cart c
  WHERE ((c.id = cart_line.cart_id) AND (c.customer_profile_id = current_customer_profile_id())))));
CREATE POLICY custom_offering_select_admin ON public.custom_offering AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY custom_offering_select_published_or_own ON public.custom_offering AS PERMISSIVE FOR SELECT TO authenticated
    USING (((publication_state = 'published'::custom_offering_state) OR (marketplace_party_id = current_marketplace_party_id())));
CREATE POLICY custom_offering_write_own ON public.custom_offering AS PERMISSIVE FOR ALL TO authenticated
    USING (((marketplace_party_id = current_marketplace_party_id()) AND current_party_is_approved()))
    WITH CHECK (((marketplace_party_id = current_marketplace_party_id()) AND current_party_is_approved()));
CREATE POLICY phase32b_custom_offering_anon_read ON public.custom_offering AS PERMISSIVE FOR SELECT TO anon
    USING ((publication_state = 'published'::custom_offering_state));
CREATE POLICY phase32b_custom_offering_anon_read_guard ON public.custom_offering AS RESTRICTIVE FOR SELECT TO anon
    USING ((publication_state = 'published'::custom_offering_state));
CREATE POLICY design_product_reference_select_own ON public.design_product_reference AS PERMISSIVE FOR SELECT TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM design d
  WHERE ((d.id = design_product_reference.design_id) AND (d.originating_user_id = auth.uid())))));
CREATE POLICY design_product_reference_write_own ON public.design_product_reference AS PERMISSIVE FOR ALL TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM design d
  WHERE ((d.id = design_product_reference.design_id) AND (d.originating_user_id = auth.uid())))))
    WITH CHECK ((EXISTS ( SELECT 1
   FROM design d
  WHERE ((d.id = design_product_reference.design_id) AND (d.originating_user_id = auth.uid())))));
CREATE POLICY furnishing_request_design_version_select ON public.furnishing_request_design_version AS PERMISSIVE FOR SELECT TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM furnishing_request fr
  WHERE ((fr.id = furnishing_request_design_version.furnishing_request_id) AND ((fr.customer_profile_id = current_customer_profile_id()) OR ((fr.lifecycle_state = 'open'::furnishing_request_state) AND current_party_is_approved()))))));
CREATE POLICY furnishing_request_design_version_write_own ON public.furnishing_request_design_version AS PERMISSIVE FOR ALL TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM furnishing_request fr
  WHERE ((fr.id = furnishing_request_design_version.furnishing_request_id) AND (fr.customer_profile_id = current_customer_profile_id())))))
    WITH CHECK ((EXISTS ( SELECT 1
   FROM furnishing_request fr
  WHERE ((fr.id = furnishing_request_design_version.furnishing_request_id) AND (fr.customer_profile_id = current_customer_profile_id())))));
CREATE POLICY marketplace_party_insert_own ON public.marketplace_party AS PERMISSIVE FOR INSERT TO authenticated
    WITH CHECK (((user_id = auth.uid()) AND (approval_state = 'pending'::party_approval_state) AND (state_reason IS NULL)));
CREATE POLICY marketplace_party_select_admin ON public.marketplace_party AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY marketplace_party_select_own ON public.marketplace_party AS PERMISSIVE FOR SELECT TO authenticated
    USING ((user_id = auth.uid()));
CREATE POLICY marketplace_party_select_public ON public.marketplace_party AS PERMISSIVE FOR SELECT TO anon, authenticated
    USING ((approval_state = 'approved'::party_approval_state));
CREATE POLICY marketplace_party_update_own ON public.marketplace_party AS PERMISSIVE FOR UPDATE TO authenticated
    USING ((user_id = auth.uid()))
    WITH CHECK ((user_id = auth.uid()));
CREATE POLICY offer_line_item_select ON public.offer_line_item AS PERMISSIVE FOR SELECT TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM offer o
  WHERE ((o.id = offer_line_item.offer_id) AND ((o.marketplace_party_id = current_marketplace_party_id()) OR (EXISTS ( SELECT 1
           FROM furnishing_request fr
          WHERE ((fr.id = o.furnishing_request_id) AND (fr.customer_profile_id = current_customer_profile_id())))))))));
CREATE POLICY offer_line_item_select_admin ON public.offer_line_item AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY offer_line_item_write_own ON public.offer_line_item AS PERMISSIVE FOR ALL TO authenticated
    USING ((EXISTS ( SELECT 1
   FROM offer o
  WHERE ((o.id = offer_line_item.offer_id) AND (o.marketplace_party_id = current_marketplace_party_id()) AND (o.lifecycle_state = 'submitted'::offer_state)))))
    WITH CHECK ((EXISTS ( SELECT 1
   FROM offer o
  WHERE ((o.id = offer_line_item.offer_id) AND (o.marketplace_party_id = current_marketplace_party_id()) AND (o.lifecycle_state = 'submitted'::offer_state)))));
CREATE POLICY party_capability_write_own ON public.party_capability AS PERMISSIVE FOR ALL TO authenticated
    USING ((marketplace_party_id = current_marketplace_party_id()))
    WITH CHECK ((marketplace_party_id = current_marketplace_party_id()));
CREATE POLICY phase32c_party_capability_admin_read ON public.party_capability AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY phase32c_party_capability_anon_read ON public.party_capability AS PERMISSIVE FOR SELECT TO anon
    USING (((EXISTS ( SELECT 1
   FROM marketplace_party capability_party
  WHERE ((capability_party.id = party_capability.marketplace_party_id) AND (capability_party.approval_state = 'approved'::party_approval_state)))) AND (EXISTS ( SELECT 1
   FROM service_type capability_service
  WHERE ((capability_service.id = party_capability.service_type_id) AND capability_service.is_active)))));
CREATE POLICY phase32c_party_capability_authenticated_read ON public.party_capability AS PERMISSIVE FOR SELECT TO authenticated
    USING (((EXISTS ( SELECT 1
   FROM marketplace_party capability_party
  WHERE ((capability_party.id = party_capability.marketplace_party_id) AND (capability_party.approval_state = 'approved'::party_approval_state)))) AND (EXISTS ( SELECT 1
   FROM service_type capability_service
  WHERE ((capability_service.id = party_capability.service_type_id) AND capability_service.is_active)))));
CREATE POLICY phase32c_party_capability_owner_read ON public.party_capability AS PERMISSIVE FOR SELECT TO authenticated
    USING ((marketplace_party_id = current_marketplace_party_id()));
CREATE POLICY purchase_order_select_admin ON public.purchase_order AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY purchase_order_select_engaged ON public.purchase_order AS PERMISSIVE FOR SELECT TO authenticated
    USING (((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id())));
CREATE POLICY purchase_order_update_party ON public.purchase_order AS PERMISSIVE FOR UPDATE TO authenticated
    USING ((marketplace_party_id = current_marketplace_party_id()))
    WITH CHECK ((marketplace_party_id = current_marketplace_party_id()));
CREATE POLICY phase32c_review_anon_safe_read ON public.review AS PERMISSIVE FOR SELECT TO anon
    USING (((((target_kind)::text = 'product'::text) AND (target_product_id IS NOT NULL) AND (target_marketplace_party_id IS NULL) AND (target_service_request_id IS NULL) AND (EXISTS ( SELECT 1
   FROM ((product reviewed_product
     JOIN marketplace_party product_party ON ((product_party.id = reviewed_product.marketplace_party_id)))
     JOIN category product_category ON ((product_category.id = reviewed_product.category_id)))
  WHERE ((reviewed_product.id = review.target_product_id) AND (reviewed_product.lifecycle_state = 'published'::product_state) AND (product_party.approval_state = 'approved'::party_approval_state) AND product_category.is_active AND (EXISTS ( SELECT 1
           FROM product_color available_color
          WHERE ((available_color.product_id = reviewed_product.id) AND (available_color.stock_quantity > 0)))))))) OR (((target_kind)::text = 'marketplace_party'::text) AND (target_product_id IS NULL) AND (target_marketplace_party_id IS NOT NULL) AND (target_service_request_id IS NULL) AND (EXISTS ( SELECT 1
   FROM marketplace_party reviewed_party
  WHERE ((reviewed_party.id = review.target_marketplace_party_id) AND (reviewed_party.approval_state = 'approved'::party_approval_state)))))));
CREATE POLICY phase32c_review_authenticated_read_guard ON public.review AS RESTRICTIVE FOR SELECT TO authenticated
    USING (((customer_profile_id = current_customer_profile_id()) OR is_admin()));
CREATE POLICY review_select_admin ON public.review AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY review_write_own ON public.review AS PERMISSIVE FOR ALL TO authenticated
    USING ((customer_profile_id = current_customer_profile_id()))
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY saved_space_all_own ON public.saved_space AS PERMISSIVE FOR ALL TO authenticated
    USING ((customer_profile_id = current_customer_profile_id()))
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY service_request_insert_own ON public.service_request AS PERMISSIVE FOR INSERT TO authenticated
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY service_request_select ON public.service_request AS PERMISSIVE FOR SELECT TO authenticated
    USING (((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id()) OR ((lifecycle_state = 'pending'::service_request_state) AND current_party_is_approved() AND (EXISTS ( SELECT 1
   FROM party_capability pc
  WHERE ((pc.marketplace_party_id = current_marketplace_party_id()) AND (pc.service_type_id = service_request.service_type_id)))))));
CREATE POLICY service_request_select_admin ON public.service_request AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_admin());
CREATE POLICY service_request_update_engaged ON public.service_request AS PERMISSIVE FOR UPDATE TO authenticated
    USING (((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id())))
    WITH CHECK (((customer_profile_id = current_customer_profile_id()) OR (marketplace_party_id = current_marketplace_party_id())));

COMMIT;
