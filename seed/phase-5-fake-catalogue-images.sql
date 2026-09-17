/*
Refresh Phase 5 seed images -- FAKE-DATA TESTING BRANCH ONLY.

Replaces the placeholder image on every SEED- product with a real
category photograph. Updates one column, inserts nothing, deletes
nothing, and matches only rows whose product carries a SEED- SKU.
Safe to run more than once.

Rendered by tests/seed_catalogue.py; do not hand-edit.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

DO $image_preflight$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.product WHERE sku LIKE 'SEED-%') THEN
        RAISE EXCEPTION 'no SEED- products found; load the seed first';
    END IF;
END
$image_preflight$;

UPDATE public.product_image AS target
SET image_url = source.image_url
FROM (VALUES
    ('7c000000-0000-4000-8000-000000001000'::uuid, 'https://images.unsplash.com/photo-1635594202056-9ea3b497e5c0?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000002000'::uuid, 'https://images.unsplash.com/photo-1552858725-2758b5fb1286?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000003000'::uuid, 'https://images.unsplash.com/photo-1617325247661-675ab4b64ae2?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000004000'::uuid, 'https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000005000'::uuid, 'https://images.unsplash.com/photo-1601276174812-63280a55656e?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000006000'::uuid, 'https://images.unsplash.com/photo-1552650272-b8a34e21bc4b?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000007000'::uuid, 'https://images.unsplash.com/photo-1556750539-dc6305f4f248?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000008000'::uuid, 'https://images.unsplash.com/photo-1564019472231-4586c552dc27?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000009000'::uuid, 'https://images.unsplash.com/photo-1614597445336-8a67e9314d91?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000010000'::uuid, 'https://images.unsplash.com/photo-1604578762246-41134e37f9cc?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000011000'::uuid, 'https://images.unsplash.com/photo-1606660023296-81d67734170a?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000012000'::uuid, 'https://images.unsplash.com/photo-1574966739987-65e38db0f7ce?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000013000'::uuid, 'https://images.unsplash.com/photo-1605239435870-67df4c54a0b3?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000014000'::uuid, 'https://images.unsplash.com/photo-1615066390971-03e4e1c36ddf?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000015000'::uuid, 'https://images.unsplash.com/photo-1602872030490-4a484a7b3ba6?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000016000'::uuid, 'https://images.unsplash.com/photo-1657524398377-567034729507?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000017000'::uuid, 'https://images.unsplash.com/photo-1567016432779-094069958ea5?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000018000'::uuid, 'https://images.unsplash.com/photo-1573866926487-a1865558a9cf?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000019000'::uuid, 'https://images.unsplash.com/photo-1512212621149-107ffe572d2f?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000020000'::uuid, 'https://images.unsplash.com/photo-1550581190-9c1c48d21d6c?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000021000'::uuid, 'https://images.unsplash.com/photo-1493663284031-b7e3aefcae8e?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000022000'::uuid, 'https://images.unsplash.com/photo-1519961655809-34fa156820ff?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000023000'::uuid, 'https://images.unsplash.com/photo-1567016376408-0226e4d0c1ea?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000024000'::uuid, 'https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000025000'::uuid, 'https://images.unsplash.com/photo-1567401893414-76b7b1e5a7a5?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000026000'::uuid, 'https://images.unsplash.com/photo-1649361811423-a55616f7ab11?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000027000'::uuid, 'https://images.unsplash.com/photo-1558997519-83ea9252edf8?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000028000'::uuid, 'https://images.unsplash.com/photo-1614631446501-abcf76949eca?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000029000'::uuid, 'https://images.unsplash.com/photo-1611048268330-53de574cae3b?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000030000'::uuid, 'https://images.unsplash.com/photo-1558769132-cb1aea458c5e?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000031000'::uuid, 'https://images.unsplash.com/photo-1567113463300-102a7eb3cb26?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000032000'::uuid, 'https://images.unsplash.com/photo-1672137233327-37b0c1049e77?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000033000'::uuid, 'https://images.unsplash.com/photo-1506439773649-6e0eb8cfb237?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000034000'::uuid, 'https://images.unsplash.com/photo-1612372606404-0ab33e7187ee?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000035000'::uuid, 'https://images.unsplash.com/photo-1581539250439-c96689b516dd?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000036000'::uuid, 'https://images.unsplash.com/photo-1598300042247-d088f8ab3a91?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000037000'::uuid, 'https://images.unsplash.com/photo-1592078615290-033ee584e267?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000038000'::uuid, 'https://images.unsplash.com/photo-1549497538-303791108f95?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000039000'::uuid, 'https://images.unsplash.com/photo-1567538096630-e0c55bd6374c?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000040000'::uuid, 'https://images.unsplash.com/photo-1580480055273-228ff5388ef8?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000041000'::uuid, 'https://images.unsplash.com/photo-1567016432779-094069958ea5?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000042000'::uuid, 'https://images.unsplash.com/photo-1552858725-2758b5fb1286?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000043000'::uuid, 'https://images.unsplash.com/photo-1581539250439-c96689b516dd?auto=format&fit=crop&w=800&h=600&q=80'),
    ('7c000000-0000-4000-8000-000000044000'::uuid, 'https://images.unsplash.com/photo-1614631446501-abcf76949eca?auto=format&fit=crop&w=800&h=600&q=80')
) AS source(id, image_url)
WHERE target.id = source.id
  AND EXISTS (
      SELECT 1 FROM public.product AS owner
      WHERE owner.id = target.product_id
        AND owner.sku LIKE 'SEED-%'
  );

COMMIT;
