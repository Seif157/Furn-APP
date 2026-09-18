-- Phase 3.2C UNDO, generated 2026-09-18 17:48:17.117395+00 from the live state before the migration.
-- Run only if 3.2C was applied and must be reversed.
BEGIN;
SET LOCAL lock_timeout = '5s';

-- snapshot check: 4 original policies found, 3.2C not applied

DROP POLICY IF EXISTS phase32c_furnishing_request_delete_own ON public.furnishing_request;
DROP POLICY IF EXISTS phase32c_furnishing_request_insert_own ON public.furnishing_request;
DROP POLICY IF EXISTS phase32c_furnishing_request_update_own ON public.furnishing_request;
DROP POLICY IF EXISTS phase32c_party_capability_admin_read ON public.party_capability;
DROP POLICY IF EXISTS phase32c_party_capability_anon_read ON public.party_capability;
DROP POLICY IF EXISTS phase32c_party_capability_authenticated_read ON public.party_capability;
DROP POLICY IF EXISTS phase32c_party_capability_owner_read ON public.party_capability;
DROP POLICY IF EXISTS phase32c_review_anon_safe_read ON public.review;
DROP POLICY IF EXISTS phase32c_review_authenticated_read_guard ON public.review;
DROP POLICY IF EXISTS phase32c_service_type_anon_read ON public.service_type;
DROP POLICY IF EXISTS phase32c_service_type_authenticated_read ON public.service_type;

DROP FUNCTION IF EXISTS public.open_furnishing_request(uuid);
DROP FUNCTION IF EXISTS public.withdraw_furnishing_request(uuid);

CREATE OR REPLACE FUNCTION public.current_customer_profile_id()
 RETURNS uuid
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
  SELECT cp.id FROM public.customer_profile cp WHERE cp.user_id = auth.uid();
$function$
;
ALTER FUNCTION public.current_customer_profile_id() OWNER TO postgres;
REVOKE ALL ON FUNCTION public.current_customer_profile_id() FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.current_customer_profile_id() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.current_customer_profile_id() TO anon;
GRANT EXECUTE ON FUNCTION public.current_customer_profile_id() TO authenticated;
GRANT EXECUTE ON FUNCTION public.current_customer_profile_id() TO service_role;

REVOKE ALL ON TABLE public.review FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.review TO anon;
GRANT DELETE ON TABLE public.review TO authenticated;
GRANT INSERT ON TABLE public.review TO authenticated;
GRANT SELECT ON TABLE public.review TO authenticated;
GRANT UPDATE ON TABLE public.review TO authenticated;

REVOKE ALL ON TABLE public.furnishing_request FROM PUBLIC, anon, authenticated;
GRANT DELETE ON TABLE public.furnishing_request TO authenticated;
GRANT INSERT ON TABLE public.furnishing_request TO authenticated;
GRANT SELECT ON TABLE public.furnishing_request TO authenticated;
GRANT UPDATE ON TABLE public.furnishing_request TO authenticated;

REVOKE ALL ON TABLE public.order_financial_position FROM PUBLIC, anon, authenticated;
GRANT DELETE ON TABLE public.order_financial_position TO anon;
GRANT INSERT ON TABLE public.order_financial_position TO anon;
GRANT MAINTAIN ON TABLE public.order_financial_position TO anon;
GRANT REFERENCES ON TABLE public.order_financial_position TO anon;
GRANT TRIGGER ON TABLE public.order_financial_position TO anon;
GRANT TRUNCATE ON TABLE public.order_financial_position TO anon;
GRANT UPDATE ON TABLE public.order_financial_position TO anon;
GRANT DELETE ON TABLE public.order_financial_position TO authenticated;
GRANT INSERT ON TABLE public.order_financial_position TO authenticated;
GRANT MAINTAIN ON TABLE public.order_financial_position TO authenticated;
GRANT REFERENCES ON TABLE public.order_financial_position TO authenticated;
GRANT SELECT ON TABLE public.order_financial_position TO authenticated;
GRANT TRIGGER ON TABLE public.order_financial_position TO authenticated;
GRANT TRUNCATE ON TABLE public.order_financial_position TO authenticated;
GRANT UPDATE ON TABLE public.order_financial_position TO authenticated;

CREATE POLICY furnishing_request_write_own ON public.furnishing_request AS PERMISSIVE FOR ALL TO authenticated
    USING ((customer_profile_id = current_customer_profile_id()))
    WITH CHECK ((customer_profile_id = current_customer_profile_id()));
CREATE POLICY party_capability_select ON public.party_capability AS PERMISSIVE FOR SELECT TO anon, authenticated
    USING (true);
CREATE POLICY review_select_public ON public.review AS PERMISSIVE FOR SELECT TO anon, authenticated
    USING (true);
CREATE POLICY service_type_select_public ON public.service_type AS PERMISSIVE FOR SELECT TO anon, authenticated
    USING (true);

COMMIT;
