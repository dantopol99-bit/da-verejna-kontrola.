-- 0006: oprava pohledu ind.indikator_k_publikaci.
-- Parametr metodiky "min_zaklad": null znamená "minimum objemu se neuplatňuje"; původní podmínka
-- (klíč existuje -> porovnání s NULL) takové výsledky nesprávně vyřazovala.

CREATE OR REPLACE VIEW ind.indikator_k_publikaci AS
SELECT v.*
  FROM ind.indikator_vysledek v
  JOIN core.metodika_verze m
    ON m.metodika_verze_id = v.metodika_verze_id
   AND m.recorded_to = 'infinity'
   AND daterange(m.valid_from, m.valid_to) @> v.vypocteno::date
 WHERE jsonb_typeof(m.parametry -> 'min_pocet_pripadu') = 'number'
   AND v.pocet_pripadu >= (m.parametry ->> 'min_pocet_pripadu')::int
   AND (v.zaklad IS NULL
        OR jsonb_typeof(m.parametry -> 'min_zaklad') IS DISTINCT FROM 'number'
        OR v.zaklad >= (m.parametry ->> 'min_zaklad')::numeric)
   AND NOT ind.obsahuje_hodnotici_slova(v.text);
