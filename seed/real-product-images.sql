/*
Replace the real products' placeholder images with real photographs.

The four real catalogue products shipped with picsum.photos URLs, which
serve a random photograph rather than furniture. This updates those five
rows and nothing else.

These are real marketplace rows, so the update is doubly bounded: it
matches only the five image ids listed, and only while they still point
at picsum.photos. Once a seller uploads a genuine photograph this
script can no longer change that row, so a later rerun cannot destroy
real content. Running it twice updates nothing the second time.

Rendered by tests/real_product_images.py; do not hand-edit.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

UPDATE public.product_image AS target
SET image_url = source.image_url
FROM (VALUES
    -- كنبة كايرو 3 مقاعد — Cairo 3-Seater Sofa (primary)
    ('2701ae27-e11c-4757-885e-530de385fa0a'::uuid, 'https://images.unsplash.com/photo-1484101403633-562f891dc89a?auto=format&fit=crop&w=800&h=600&q=80'),
    -- كنبة كايرو 3 مقاعد — Cairo 3-Seater Sofa (secondary)
    ('c7d02dc5-e53c-412e-9117-b712d5dacc15'::uuid, 'https://images.unsplash.com/photo-1590251024078-8a6d9f90b02d?auto=format&fit=crop&w=800&h=600&q=80'),
    -- سرير كينج خشب — King Wooden Bed
    ('fe2eed3a-da45-4266-9c28-46444de65dc0'::uuid, 'https://images.unsplash.com/photo-1560185893-a55cbc8c57e8?auto=format&fit=crop&w=800&h=600&q=80'),
    -- طاولة سفرة 6 كراسي — 6-Seater Dining Set
    ('00cfd813-4632-4648-941c-c76144ef288a'::uuid, 'https://images.unsplash.com/photo-1517870662726-c1d98ee36250?auto=format&fit=crop&w=800&h=600&q=80'),
    -- دولاب 4 ضلفة — 4-Door Wardrobe
    ('d88fc80e-6771-46cc-84d6-044151e1cd67'::uuid, 'https://images.unsplash.com/photo-1509319117193-57bab727e09d?auto=format&fit=crop&w=800&h=600&q=80')
) AS source(id, image_url)
WHERE target.id = source.id
  AND target.image_url LIKE '%picsum.photos%';

COMMIT;
