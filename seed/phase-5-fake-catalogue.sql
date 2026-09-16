/*
Phase 5 fake catalogue seed -- FAKE-DATA TESTING BRANCH ONLY.

Inserts 44 SEED- products: 41 recommendation-eligible (40 with
dimensions and one without), plus one draft, one hidden, and one
published without stock; their colours; and one placeholder image each,
under the first approved
seller. Rendered by tests/seed_catalogue.py; do not hand-edit. Remove with
seed/phase-5-fake-catalogue-remove.sql. Never run against production.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

DO $seed_preflight$
BEGIN
    IF (
        SELECT count(*) FROM public.category
        WHERE name IN ('Beds — أسرّة', 'Dining — سفرة', 'Sofas — كنب', 'Wardrobes — دواليب', 'Chairs — كراسي')
          AND is_active
    ) <> 5 THEN
        RAISE EXCEPTION 'seed requires the five active bilingual categories';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.marketplace_party
        WHERE approval_state = 'approved'::public.party_approval_state
    ) THEN
        RAISE EXCEPTION 'seed requires an approved seller';
    END IF;
    IF EXISTS (SELECT 1 FROM public.product WHERE sku LIKE 'SEED-%') THEN
        RAISE EXCEPTION 'seed products already exist; run the remove script first';
    END IF;
END
$seed_preflight$;

INSERT INTO public.product (
    id, marketplace_party_id, category_id, name, description, price,
    discount_price, width_cm, height_cm, depth_cm, weight_kg, materials,
    lifecycle_state, sku
)
SELECT
    seed.id::uuid,
    (
        SELECT party.id FROM public.marketplace_party AS party
        WHERE party.approval_state = 'approved'::public.party_approval_state
        ORDER BY party.id LIMIT 1
    ),
    category.id,
    seed.name, seed.description, seed.price, seed.discount_price,
    seed.width_cm, seed.height_cm, seed.depth_cm, seed.weight_kg,
    seed.materials, seed.lifecycle_state::public.product_state, seed.sku
FROM (
    VALUES
        ('7a000000-0000-4000-8000-000000000001', 'Beds — أسرّة', 'سرير مودرن 160', 'Modern platform bed frame with upholstered headboard.', 12000, NULL, 170, 110, 210, 62, ARRAY['خشب زان', 'قماش']::text[], 'published', 'SEED-001'),
        ('7a000000-0000-4000-8000-000000000002', 'Beds — أسرّة', 'سرير كلاسيك 180', 'Classic carved bed frame in solid beech.', 18500, NULL, 190, 130, 215, 78, ARRAY['خشب زان']::text[], 'published', 'SEED-002'),
        ('7a000000-0000-4000-8000-000000000003', 'Beds — أسرّة', 'سرير اسكندنافي 140', 'Scandinavian bed with slatted headboard and low profile.', 9800, 8330, 150, 95, 205, 48, ARRAY['خشب']::text[], 'published', 'SEED-003'),
        ('7a000000-0000-4000-8000-000000000004', 'Beds — أسرّة', 'سرير بتخزين 160', 'Storage bed with hydraulic lift and fabric cover.', 15900, NULL, 172, 105, 212, 85, ARRAY['mdf', 'قماش', 'إسفنج']::text[], 'published', 'SEED-004'),
        ('7a000000-0000-4000-8000-000000000005', 'Beds — أسرّة', 'سرير معدن 120', 'Industrial single bed with a black metal frame.', 6400, NULL, 128, 100, 200, NULL, ARRAY['معدن']::text[], 'published', 'SEED-005'),
        ('7a000000-0000-4000-8000-000000000006', 'Beds — أسرّة', 'سرير قطيفة 180', 'Velvet upholstered king bed with a tall headboard.', 21000, 17850, 195, 140, 220, 90, ARRAY['قطيفة', 'إسفنج', 'خشب']::text[], 'published', 'SEED-006'),
        ('7a000000-0000-4000-8000-000000000007', 'Beds — أسرّة', 'سرير جلد 160', 'Leather-look queen bed with a padded headboard.', 17200, NULL, 175, 100, 215, 72, ARRAY['جلد', 'mdf']::text[], 'published', 'SEED-007'),
        ('7a000000-0000-4000-8000-000000000008', 'Beds — أسرّة', 'سرير بلوط 180', 'Oak king bed with a floating nightstand design.', 24500, NULL, 200, 90, 220, 95, ARRAY['بلوط']::text[], 'published', 'SEED-008'),
        ('7a000000-0000-4000-8000-000000000009', 'Dining — سفرة', 'طاولة سفرة 6 كراسي', 'Six-seat dining table with a tempered glass top.', 14500, 12325, 160, 76, 90, 55, ARRAY['زجاج', 'معدن']::text[], 'published', 'SEED-009'),
        ('7a000000-0000-4000-8000-000000000010', 'Dining — سفرة', 'سفرة كلاسيك 8 كراسي', 'Eight-seat classic dining set in carved beech.', 32000, NULL, 220, 78, 100, NULL, ARRAY['خشب زان']::text[], 'published', 'SEED-010'),
        ('7a000000-0000-4000-8000-000000000011', 'Dining — سفرة', 'طاولة سفرة خشب 4 كراسي', 'Four-seat round dining table in natural wood.', 8900, NULL, 110, 75, 110, 32, ARRAY['خشب']::text[], 'published', 'SEED-011'),
        ('7a000000-0000-4000-8000-000000000012', 'Dining — سفرة', 'سفرة صناعي 6 كراسي', 'Industrial dining table with a reclaimed wood top.', 12800, 10880, 180, 76, 85, 68, ARRAY['خشب', 'معدن']::text[], 'published', 'SEED-012'),
        ('7a000000-0000-4000-8000-000000000013', 'Dining — سفرة', 'طاولة سفرة قابلة للتمديد', 'Extendable dining table seating six to eight.', 16700, NULL, 160, 76, 90, 74, ARRAY['mdf']::text[], 'published', 'SEED-013'),
        ('7a000000-0000-4000-8000-000000000014', 'Dining — سفرة', 'سفرة رخامية 6 كراسي', 'Marble-look dining table with brass-tone legs.', 27500, NULL, 200, 76, 100, 110, ARRAY['mdf', 'معدن']::text[], 'published', 'SEED-014'),
        ('7a000000-0000-4000-8000-000000000015', 'Dining — سفرة', 'طاولة سفرة بلوط 6 كراسي', 'Oak dining table with tapered legs.', 19800, 16830, 180, 75, 90, NULL, ARRAY['بلوط']::text[], 'published', 'SEED-015'),
        ('7a000000-0000-4000-8000-000000000016', 'Dining — سفرة', 'سفرة مودرن 4 كراسي', 'Compact modern dining set for small apartments.', 7600, NULL, 120, 76, 80, 40, ARRAY['mdf', 'قماش']::text[], 'published', 'SEED-016'),
        ('7a000000-0000-4000-8000-000000000017', 'Sofas — كنب', 'كنبة مودرن 3 مقاعد', 'Modern three-seat sofa with deep cushions.', 13500, NULL, 220, 85, 95, 58, ARRAY['خشب زان', 'قماش', 'إسفنج']::text[], 'published', 'SEED-017'),
        ('7a000000-0000-4000-8000-000000000018', 'Sofas — كنب', 'كنبة كلاسيك 3 مقاعد', 'Classic three-seat sofa with carved wooden arms.', 19500, 16575, 230, 100, 95, 75, ARRAY['خشب زان', 'قطيفة']::text[], 'published', 'SEED-018'),
        ('7a000000-0000-4000-8000-000000000019', 'Sofas — كنب', 'كنبة اسكندنافي مقعدين', 'Scandinavian two-seat sofa on tapered legs.', 9900, NULL, 165, 82, 88, 42, ARRAY['خشب', 'قطن']::text[], 'published', 'SEED-019'),
        ('7a000000-0000-4000-8000-000000000020', 'Sofas — كنب', 'كنبة ركنة', 'L-shaped corner sofa with a reversible chaise.', 24000, NULL, 280, 88, 180, NULL, ARRAY['mdf', 'قماش', 'إسفنج']::text[], 'published', 'SEED-020'),
        ('7a000000-0000-4000-8000-000000000021', 'Sofas — كنب', 'كنبة جلد مقعدين', 'Industrial two-seat sofa in leather-look upholstery.', 11800, 10030, 170, 80, 90, 50, ARRAY['جلد', 'معدن']::text[], 'published', 'SEED-021'),
        ('7a000000-0000-4000-8000-000000000022', 'Sofas — كنب', 'كنبة سرير', 'Sofa bed that converts to a double bed.', 14200, NULL, 200, 90, 100, 70, ARRAY['mdf', 'قماش', 'إسفنج']::text[], 'published', 'SEED-022'),
        ('7a000000-0000-4000-8000-000000000023', 'Sofas — كنب', 'كنبة قطيفة 3 مقاعد', 'Velvet three-seat sofa with tufted back.', 21500, NULL, 225, 95, 95, 80, ARRAY['قطيفة', 'خشب زان']::text[], 'published', 'SEED-023'),
        ('7a000000-0000-4000-8000-000000000024', 'Sofas — كنب', 'كنبة كتان 3 مقاعد', 'Linen three-seat sofa with a slim frame.', 15800, 13430, 215, 84, 92, 55, ARRAY['كتان', 'خشب']::text[], 'published', 'SEED-024'),
        ('7a000000-0000-4000-8000-000000000025', 'Wardrobes — دواليب', 'دولاب 3 ضلف', 'Three-door wardrobe with a mirrored centre panel.', 16800, NULL, 150, 210, 60, NULL, ARRAY['mdf']::text[], 'published', 'SEED-025'),
        ('7a000000-0000-4000-8000-000000000026', 'Wardrobes — دواليب', 'دولاب كلاسيك 4 ضلف', 'Four-door classic wardrobe in carved beech.', 28900, NULL, 200, 220, 65, 160, ARRAY['خشب زان']::text[], 'published', 'SEED-026'),
        ('7a000000-0000-4000-8000-000000000027', 'Wardrobes — دواليب', 'دولاب اسكندنافي 2 ضلف', 'Two-door Scandinavian wardrobe with open shelving.', 10900, 9265, 100, 200, 55, 70, ARRAY['خشب']::text[], 'published', 'SEED-027'),
        ('7a000000-0000-4000-8000-000000000028', 'Wardrobes — دواليب', 'دولاب جرار 2 ضلف', 'Sliding-door wardrobe with a full-height mirror.', 22500, NULL, 180, 215, 62, 140, ARRAY['mdf', 'زجاج']::text[], 'published', 'SEED-028'),
        ('7a000000-0000-4000-8000-000000000029', 'Wardrobes — دواليب', 'دولاب معدن مفتوح', 'Open industrial wardrobe with a metal frame.', 7400, NULL, 120, 190, 50, 38, ARRAY['معدن', 'خشب']::text[], 'published', 'SEED-029'),
        ('7a000000-0000-4000-8000-000000000030', 'Wardrobes — دواليب', 'دولاب 5 ضلف', 'Five-door wardrobe with integrated drawers.', 31000, 26350, 250, 220, 62, NULL, ARRAY['mdf']::text[], 'published', 'SEED-030'),
        ('7a000000-0000-4000-8000-000000000031', 'Wardrobes — دواليب', 'دولاب بلوط 3 ضلف', 'Oak three-door wardrobe with brass handles.', 34500, NULL, 160, 215, 60, 150, ARRAY['بلوط']::text[], 'published', 'SEED-031'),
        ('7a000000-0000-4000-8000-000000000032', 'Wardrobes — دواليب', 'دولاب أطفال 2 ضلف', 'Compact children''s wardrobe with rounded edges.', 6900, NULL, 90, 170, 50, 45, ARRAY['mdf']::text[], 'published', 'SEED-032'),
        ('7a000000-0000-4000-8000-000000000033', 'Chairs — كراسي', 'كرسي سفرة مودرن', 'Modern dining chair with a curved fabric seat.', 1900, 1615, 46, 88, 52, 6, ARRAY['معدن', 'قماش']::text[], 'published', 'SEED-033'),
        ('7a000000-0000-4000-8000-000000000034', 'Chairs — كراسي', 'كرسي كلاسيك منجد', 'Classic upholstered chair with carved legs.', 3400, NULL, 50, 100, 55, 9, ARRAY['خشب زان', 'قطيفة']::text[], 'published', 'SEED-034'),
        ('7a000000-0000-4000-8000-000000000035', 'Chairs — كراسي', 'كرسي خشب اسكندنافي', 'Scandinavian wooden chair with a woven seat.', 2200, NULL, 45, 82, 50, NULL, ARRAY['خشب', 'قطن']::text[], 'published', 'SEED-035'),
        ('7a000000-0000-4000-8000-000000000036', 'Chairs — كراسي', 'كرسي معدن صناعي', 'Stackable industrial metal chair.', 1200, 1020, 44, 84, 50, 5, ARRAY['معدن']::text[], 'published', 'SEED-036'),
        ('7a000000-0000-4000-8000-000000000037', 'Chairs — كراسي', 'كرسي مكتب', 'Ergonomic office chair with lumbar support.', 4800, NULL, 62, 118, 62, 14, ARRAY['معدن', 'قماش', 'إسفنج']::text[], 'published', 'SEED-037'),
        ('7a000000-0000-4000-8000-000000000038', 'Chairs — كراسي', 'كرسي جلد بذراعين', 'Leather-look armchair for reading corners.', 7900, NULL, 80, 95, 85, 24, ARRAY['جلد', 'خشب']::text[], 'published', 'SEED-038'),
        ('7a000000-0000-4000-8000-000000000039', 'Chairs — كراسي', 'كرسي هزاز', 'Rocking chair with a padded linen cushion.', 5600, 4760, 70, 100, 95, 16, ARRAY['خشب', 'كتان']::text[], 'published', 'SEED-039'),
        ('7a000000-0000-4000-8000-000000000040', 'Chairs — كراسي', 'كرسي طعام بلوط', 'Oak dining chair with a slim backrest.', 2900, NULL, 47, 86, 52, NULL, ARRAY['بلوط']::text[], 'published', 'SEED-040'),
        ('7a000000-0000-4000-8000-000000000041', 'Sofas — كنب', 'كنبة مسودة', 'Draft sofa that must never appear in results.', 9000, NULL, 200, 85, 90, 50, ARRAY['قماش']::text[], 'draft', 'SEED-041'),
        ('7a000000-0000-4000-8000-000000000042', 'Beds — أسرّة', 'سرير مخفي', 'Hidden bed that must never appear in results.', 15000, NULL, 180, 120, 210, 70, ARRAY['خشب زان']::text[], 'hidden', 'SEED-042'),
        ('7a000000-0000-4000-8000-000000000043', 'Chairs — كراسي', 'كرسي نفد', 'Published chair with no stock in any colour.', 2100, NULL, 46, 88, 52, 6, ARRAY['معدن', 'قماش']::text[], 'published', 'SEED-043'),
        ('7a000000-0000-4000-8000-000000000044', 'Wardrobes — دواليب', 'دولاب بدون مقاسات', 'Published wardrobe with unknown dimensions.', 12000, NULL, NULL, NULL, NULL, NULL, ARRAY['mdf']::text[], 'published', 'SEED-044')
) AS seed(
    id, category_name, name, description, price, discount_price, width_cm,
    height_cm, depth_cm, weight_kg, materials, lifecycle_state, sku
)
JOIN public.category ON category.name = seed.category_name;

INSERT INTO public.product_color (
    id, product_id, color_value, stock_quantity, display_order
)
VALUES
    ('7b000000-0000-4000-8000-000000001000'::uuid, '7a000000-0000-4000-8000-000000000001'::uuid, 'بيج — beige', 2, 0),
    ('7b000000-0000-4000-8000-000000001001'::uuid, '7a000000-0000-4000-8000-000000000001'::uuid, 'رمادي — grey', 3, 1),
    ('7b000000-0000-4000-8000-000000002000'::uuid, '7a000000-0000-4000-8000-000000000002'::uuid, 'بني — brown', 3, 0),
    ('7b000000-0000-4000-8000-000000002001'::uuid, '7a000000-0000-4000-8000-000000000002'::uuid, 'بني غامق — dark brown', 4, 1),
    ('7b000000-0000-4000-8000-000000003000'::uuid, '7a000000-0000-4000-8000-000000000003'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000003001'::uuid, '7a000000-0000-4000-8000-000000000003'::uuid, 'أبيض — white', 1, 1),
    ('7b000000-0000-4000-8000-000000004000'::uuid, '7a000000-0000-4000-8000-000000000004'::uuid, 'رمادي — grey', 1, 0),
    ('7b000000-0000-4000-8000-000000004001'::uuid, '7a000000-0000-4000-8000-000000000004'::uuid, 'كحلي — navy', 2, 1),
    ('7b000000-0000-4000-8000-000000005000'::uuid, '7a000000-0000-4000-8000-000000000005'::uuid, 'أسود — black', 2, 0),
    ('7b000000-0000-4000-8000-000000006000'::uuid, '7a000000-0000-4000-8000-000000000006'::uuid, 'كحلي — navy', 3, 0),
    ('7b000000-0000-4000-8000-000000006001'::uuid, '7a000000-0000-4000-8000-000000000006'::uuid, 'كريمي — cream', 4, 1),
    ('7b000000-0000-4000-8000-000000007000'::uuid, '7a000000-0000-4000-8000-000000000007'::uuid, 'أبيض — white', 4, 0),
    ('7b000000-0000-4000-8000-000000007001'::uuid, '7a000000-0000-4000-8000-000000000007'::uuid, 'أسود — black', 1, 1),
    ('7b000000-0000-4000-8000-000000008000'::uuid, '7a000000-0000-4000-8000-000000000008'::uuid, 'طبيعي — natural', 1, 0),
    ('7b000000-0000-4000-8000-000000009000'::uuid, '7a000000-0000-4000-8000-000000000009'::uuid, 'أسود — black', 2, 0),
    ('7b000000-0000-4000-8000-000000009001'::uuid, '7a000000-0000-4000-8000-000000000009'::uuid, 'أبيض — white', 3, 1),
    ('7b000000-0000-4000-8000-000000010000'::uuid, '7a000000-0000-4000-8000-000000000010'::uuid, 'بني — brown', 3, 0),
    ('7b000000-0000-4000-8000-000000010001'::uuid, '7a000000-0000-4000-8000-000000000010'::uuid, 'بني غامق — dark brown', 4, 1),
    ('7b000000-0000-4000-8000-000000011000'::uuid, '7a000000-0000-4000-8000-000000000011'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000012000'::uuid, '7a000000-0000-4000-8000-000000000012'::uuid, 'بني — brown', 1, 0),
    ('7b000000-0000-4000-8000-000000012001'::uuid, '7a000000-0000-4000-8000-000000000012'::uuid, 'أسود — black', 2, 1),
    ('7b000000-0000-4000-8000-000000013000'::uuid, '7a000000-0000-4000-8000-000000000013'::uuid, 'أبيض — white', 2, 0),
    ('7b000000-0000-4000-8000-000000013001'::uuid, '7a000000-0000-4000-8000-000000000013'::uuid, 'وينجيه — wenge', 3, 1),
    ('7b000000-0000-4000-8000-000000014000'::uuid, '7a000000-0000-4000-8000-000000000014'::uuid, 'كريمي — cream', 3, 0),
    ('7b000000-0000-4000-8000-000000014001'::uuid, '7a000000-0000-4000-8000-000000000014'::uuid, 'رمادي — grey', 4, 1),
    ('7b000000-0000-4000-8000-000000015000'::uuid, '7a000000-0000-4000-8000-000000000015'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000015001'::uuid, '7a000000-0000-4000-8000-000000000015'::uuid, 'أبيض — white', 1, 1),
    ('7b000000-0000-4000-8000-000000016000'::uuid, '7a000000-0000-4000-8000-000000000016'::uuid, 'رمادي — grey', 1, 0),
    ('7b000000-0000-4000-8000-000000016001'::uuid, '7a000000-0000-4000-8000-000000000016'::uuid, 'بيج — beige', 2, 1),
    ('7b000000-0000-4000-8000-000000017000'::uuid, '7a000000-0000-4000-8000-000000000017'::uuid, 'بيج — beige', 2, 0),
    ('7b000000-0000-4000-8000-000000017001'::uuid, '7a000000-0000-4000-8000-000000000017'::uuid, 'رمادي — grey', 3, 1),
    ('7b000000-0000-4000-8000-000000018000'::uuid, '7a000000-0000-4000-8000-000000000018'::uuid, 'بني غامق — dark brown', 3, 0),
    ('7b000000-0000-4000-8000-000000018001'::uuid, '7a000000-0000-4000-8000-000000000018'::uuid, 'كحلي — navy', 4, 1),
    ('7b000000-0000-4000-8000-000000019000'::uuid, '7a000000-0000-4000-8000-000000000019'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000019001'::uuid, '7a000000-0000-4000-8000-000000000019'::uuid, 'رمادي — grey', 1, 1),
    ('7b000000-0000-4000-8000-000000020000'::uuid, '7a000000-0000-4000-8000-000000000020'::uuid, 'رمادي — grey', 1, 0),
    ('7b000000-0000-4000-8000-000000020001'::uuid, '7a000000-0000-4000-8000-000000000020'::uuid, 'بيج — beige', 2, 1),
    ('7b000000-0000-4000-8000-000000020002'::uuid, '7a000000-0000-4000-8000-000000000020'::uuid, 'كحلي — navy', 3, 2),
    ('7b000000-0000-4000-8000-000000021000'::uuid, '7a000000-0000-4000-8000-000000000021'::uuid, 'أسود — black', 2, 0),
    ('7b000000-0000-4000-8000-000000021001'::uuid, '7a000000-0000-4000-8000-000000000021'::uuid, 'بني — brown', 3, 1),
    ('7b000000-0000-4000-8000-000000022000'::uuid, '7a000000-0000-4000-8000-000000000022'::uuid, 'رمادي — grey', 3, 0),
    ('7b000000-0000-4000-8000-000000022001'::uuid, '7a000000-0000-4000-8000-000000000022'::uuid, 'كريمي — cream', 4, 1),
    ('7b000000-0000-4000-8000-000000023000'::uuid, '7a000000-0000-4000-8000-000000000023'::uuid, 'كحلي — navy', 4, 0),
    ('7b000000-0000-4000-8000-000000023001'::uuid, '7a000000-0000-4000-8000-000000000023'::uuid, 'كريمي — cream', 1, 1),
    ('7b000000-0000-4000-8000-000000023002'::uuid, '7a000000-0000-4000-8000-000000000023'::uuid, 'بيج — beige', 2, 2),
    ('7b000000-0000-4000-8000-000000024000'::uuid, '7a000000-0000-4000-8000-000000000024'::uuid, 'أبيض — white', 1, 0),
    ('7b000000-0000-4000-8000-000000024001'::uuid, '7a000000-0000-4000-8000-000000000024'::uuid, 'بيج — beige', 2, 1),
    ('7b000000-0000-4000-8000-000000025000'::uuid, '7a000000-0000-4000-8000-000000000025'::uuid, 'أبيض — white', 2, 0),
    ('7b000000-0000-4000-8000-000000025001'::uuid, '7a000000-0000-4000-8000-000000000025'::uuid, 'وينجيه — wenge', 3, 1),
    ('7b000000-0000-4000-8000-000000026000'::uuid, '7a000000-0000-4000-8000-000000000026'::uuid, 'بني — brown', 3, 0),
    ('7b000000-0000-4000-8000-000000026001'::uuid, '7a000000-0000-4000-8000-000000000026'::uuid, 'بني غامق — dark brown', 4, 1),
    ('7b000000-0000-4000-8000-000000027000'::uuid, '7a000000-0000-4000-8000-000000000027'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000027001'::uuid, '7a000000-0000-4000-8000-000000000027'::uuid, 'أبيض — white', 1, 1),
    ('7b000000-0000-4000-8000-000000028000'::uuid, '7a000000-0000-4000-8000-000000000028'::uuid, 'أبيض — white', 1, 0),
    ('7b000000-0000-4000-8000-000000028001'::uuid, '7a000000-0000-4000-8000-000000000028'::uuid, 'رمادي — grey', 2, 1),
    ('7b000000-0000-4000-8000-000000029000'::uuid, '7a000000-0000-4000-8000-000000000029'::uuid, 'أسود — black', 2, 0),
    ('7b000000-0000-4000-8000-000000030000'::uuid, '7a000000-0000-4000-8000-000000000030'::uuid, 'كريمي — cream', 3, 0),
    ('7b000000-0000-4000-8000-000000030001'::uuid, '7a000000-0000-4000-8000-000000000030'::uuid, 'وينجيه — wenge', 4, 1),
    ('7b000000-0000-4000-8000-000000031000'::uuid, '7a000000-0000-4000-8000-000000000031'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000032000'::uuid, '7a000000-0000-4000-8000-000000000032'::uuid, 'أبيض — white', 1, 0),
    ('7b000000-0000-4000-8000-000000032001'::uuid, '7a000000-0000-4000-8000-000000000032'::uuid, 'بيج — beige', 2, 1),
    ('7b000000-0000-4000-8000-000000033000'::uuid, '7a000000-0000-4000-8000-000000000033'::uuid, 'رمادي — grey', 2, 0),
    ('7b000000-0000-4000-8000-000000033001'::uuid, '7a000000-0000-4000-8000-000000000033'::uuid, 'بيج — beige', 3, 1),
    ('7b000000-0000-4000-8000-000000034000'::uuid, '7a000000-0000-4000-8000-000000000034'::uuid, 'كحلي — navy', 3, 0),
    ('7b000000-0000-4000-8000-000000034001'::uuid, '7a000000-0000-4000-8000-000000000034'::uuid, 'بني غامق — dark brown', 4, 1),
    ('7b000000-0000-4000-8000-000000035000'::uuid, '7a000000-0000-4000-8000-000000000035'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000035001'::uuid, '7a000000-0000-4000-8000-000000000035'::uuid, 'أبيض — white', 1, 1),
    ('7b000000-0000-4000-8000-000000036000'::uuid, '7a000000-0000-4000-8000-000000000036'::uuid, 'أسود — black', 1, 0),
    ('7b000000-0000-4000-8000-000000037000'::uuid, '7a000000-0000-4000-8000-000000000037'::uuid, 'أسود — black', 2, 0),
    ('7b000000-0000-4000-8000-000000037001'::uuid, '7a000000-0000-4000-8000-000000000037'::uuid, 'رمادي — grey', 3, 1),
    ('7b000000-0000-4000-8000-000000038000'::uuid, '7a000000-0000-4000-8000-000000000038'::uuid, 'بني — brown', 3, 0),
    ('7b000000-0000-4000-8000-000000038001'::uuid, '7a000000-0000-4000-8000-000000000038'::uuid, 'أسود — black', 4, 1),
    ('7b000000-0000-4000-8000-000000039000'::uuid, '7a000000-0000-4000-8000-000000000039'::uuid, 'طبيعي — natural', 4, 0),
    ('7b000000-0000-4000-8000-000000039001'::uuid, '7a000000-0000-4000-8000-000000000039'::uuid, 'كريمي — cream', 1, 1),
    ('7b000000-0000-4000-8000-000000040000'::uuid, '7a000000-0000-4000-8000-000000000040'::uuid, 'طبيعي — natural', 1, 0),
    ('7b000000-0000-4000-8000-000000040001'::uuid, '7a000000-0000-4000-8000-000000000040'::uuid, 'أبيض — white', 2, 1),
    ('7b000000-0000-4000-8000-000000041000'::uuid, '7a000000-0000-4000-8000-000000000041'::uuid, 'رمادي — grey', 3, 0),
    ('7b000000-0000-4000-8000-000000042000'::uuid, '7a000000-0000-4000-8000-000000000042'::uuid, 'بني — brown', 2, 0),
    ('7b000000-0000-4000-8000-000000043000'::uuid, '7a000000-0000-4000-8000-000000000043'::uuid, 'رمادي — grey', 0, 0),
    ('7b000000-0000-4000-8000-000000043001'::uuid, '7a000000-0000-4000-8000-000000000043'::uuid, 'أسود — black', 0, 1),
    ('7b000000-0000-4000-8000-000000044000'::uuid, '7a000000-0000-4000-8000-000000000044'::uuid, 'أبيض — white', 2, 0);

INSERT INTO public.product_image (
    id, product_id, image_url, display_order, is_primary, product_color_id
)
VALUES
    ('7c000000-0000-4000-8000-000000001000'::uuid, '7a000000-0000-4000-8000-000000000001'::uuid, 'https://placehold.co/800x600?text=SEED-001', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000002000'::uuid, '7a000000-0000-4000-8000-000000000002'::uuid, 'https://placehold.co/800x600?text=SEED-002', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000003000'::uuid, '7a000000-0000-4000-8000-000000000003'::uuid, 'https://placehold.co/800x600?text=SEED-003', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000004000'::uuid, '7a000000-0000-4000-8000-000000000004'::uuid, 'https://placehold.co/800x600?text=SEED-004', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000005000'::uuid, '7a000000-0000-4000-8000-000000000005'::uuid, 'https://placehold.co/800x600?text=SEED-005', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000006000'::uuid, '7a000000-0000-4000-8000-000000000006'::uuid, 'https://placehold.co/800x600?text=SEED-006', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000007000'::uuid, '7a000000-0000-4000-8000-000000000007'::uuid, 'https://placehold.co/800x600?text=SEED-007', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000008000'::uuid, '7a000000-0000-4000-8000-000000000008'::uuid, 'https://placehold.co/800x600?text=SEED-008', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000009000'::uuid, '7a000000-0000-4000-8000-000000000009'::uuid, 'https://placehold.co/800x600?text=SEED-009', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000010000'::uuid, '7a000000-0000-4000-8000-000000000010'::uuid, 'https://placehold.co/800x600?text=SEED-010', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000011000'::uuid, '7a000000-0000-4000-8000-000000000011'::uuid, 'https://placehold.co/800x600?text=SEED-011', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000012000'::uuid, '7a000000-0000-4000-8000-000000000012'::uuid, 'https://placehold.co/800x600?text=SEED-012', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000013000'::uuid, '7a000000-0000-4000-8000-000000000013'::uuid, 'https://placehold.co/800x600?text=SEED-013', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000014000'::uuid, '7a000000-0000-4000-8000-000000000014'::uuid, 'https://placehold.co/800x600?text=SEED-014', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000015000'::uuid, '7a000000-0000-4000-8000-000000000015'::uuid, 'https://placehold.co/800x600?text=SEED-015', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000016000'::uuid, '7a000000-0000-4000-8000-000000000016'::uuid, 'https://placehold.co/800x600?text=SEED-016', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000017000'::uuid, '7a000000-0000-4000-8000-000000000017'::uuid, 'https://placehold.co/800x600?text=SEED-017', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000018000'::uuid, '7a000000-0000-4000-8000-000000000018'::uuid, 'https://placehold.co/800x600?text=SEED-018', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000019000'::uuid, '7a000000-0000-4000-8000-000000000019'::uuid, 'https://placehold.co/800x600?text=SEED-019', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000020000'::uuid, '7a000000-0000-4000-8000-000000000020'::uuid, 'https://placehold.co/800x600?text=SEED-020', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000021000'::uuid, '7a000000-0000-4000-8000-000000000021'::uuid, 'https://placehold.co/800x600?text=SEED-021', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000022000'::uuid, '7a000000-0000-4000-8000-000000000022'::uuid, 'https://placehold.co/800x600?text=SEED-022', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000023000'::uuid, '7a000000-0000-4000-8000-000000000023'::uuid, 'https://placehold.co/800x600?text=SEED-023', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000024000'::uuid, '7a000000-0000-4000-8000-000000000024'::uuid, 'https://placehold.co/800x600?text=SEED-024', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000025000'::uuid, '7a000000-0000-4000-8000-000000000025'::uuid, 'https://placehold.co/800x600?text=SEED-025', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000026000'::uuid, '7a000000-0000-4000-8000-000000000026'::uuid, 'https://placehold.co/800x600?text=SEED-026', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000027000'::uuid, '7a000000-0000-4000-8000-000000000027'::uuid, 'https://placehold.co/800x600?text=SEED-027', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000028000'::uuid, '7a000000-0000-4000-8000-000000000028'::uuid, 'https://placehold.co/800x600?text=SEED-028', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000029000'::uuid, '7a000000-0000-4000-8000-000000000029'::uuid, 'https://placehold.co/800x600?text=SEED-029', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000030000'::uuid, '7a000000-0000-4000-8000-000000000030'::uuid, 'https://placehold.co/800x600?text=SEED-030', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000031000'::uuid, '7a000000-0000-4000-8000-000000000031'::uuid, 'https://placehold.co/800x600?text=SEED-031', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000032000'::uuid, '7a000000-0000-4000-8000-000000000032'::uuid, 'https://placehold.co/800x600?text=SEED-032', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000033000'::uuid, '7a000000-0000-4000-8000-000000000033'::uuid, 'https://placehold.co/800x600?text=SEED-033', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000034000'::uuid, '7a000000-0000-4000-8000-000000000034'::uuid, 'https://placehold.co/800x600?text=SEED-034', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000035000'::uuid, '7a000000-0000-4000-8000-000000000035'::uuid, 'https://placehold.co/800x600?text=SEED-035', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000036000'::uuid, '7a000000-0000-4000-8000-000000000036'::uuid, 'https://placehold.co/800x600?text=SEED-036', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000037000'::uuid, '7a000000-0000-4000-8000-000000000037'::uuid, 'https://placehold.co/800x600?text=SEED-037', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000038000'::uuid, '7a000000-0000-4000-8000-000000000038'::uuid, 'https://placehold.co/800x600?text=SEED-038', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000039000'::uuid, '7a000000-0000-4000-8000-000000000039'::uuid, 'https://placehold.co/800x600?text=SEED-039', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000040000'::uuid, '7a000000-0000-4000-8000-000000000040'::uuid, 'https://placehold.co/800x600?text=SEED-040', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000041000'::uuid, '7a000000-0000-4000-8000-000000000041'::uuid, 'https://placehold.co/800x600?text=SEED-041', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000042000'::uuid, '7a000000-0000-4000-8000-000000000042'::uuid, 'https://placehold.co/800x600?text=SEED-042', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000043000'::uuid, '7a000000-0000-4000-8000-000000000043'::uuid, 'https://placehold.co/800x600?text=SEED-043', 0, true, NULL),
    ('7c000000-0000-4000-8000-000000044000'::uuid, '7a000000-0000-4000-8000-000000000044'::uuid, 'https://placehold.co/800x600?text=SEED-044', 0, true, NULL);

COMMIT;
