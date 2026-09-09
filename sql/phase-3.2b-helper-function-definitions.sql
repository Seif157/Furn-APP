/*
Phase 3.2B helper-function diagnostic.

Run this read-only statement in the Supabase SQL Editor. It returns the exact
deployed definitions needed to harden the three SECURITY DEFINER functions
without inventing their behavior. It reads PostgreSQL metadata only.
*/

WITH expected_functions(function_name, display_order) AS (
    VALUES
        ('is_admin'::name, 1),
        ('current_marketplace_party_id'::name, 2),
        ('current_party_is_approved'::name, 3)
)
SELECT
    expected.display_order,
    expected.function_name AS expected_function_name,
    function_row.oid IS NOT NULL AS function_present,
    pg_catalog.pg_get_function_identity_arguments(function_row.oid)
        AS identity_arguments,
    pg_catalog.pg_get_functiondef(function_row.oid) AS function_definition
FROM expected_functions AS expected
LEFT JOIN pg_catalog.pg_proc AS function_row
    ON function_row.proname = expected.function_name
   AND function_row.pronamespace = 'public'::regnamespace
ORDER BY expected.display_order, identity_arguments;
