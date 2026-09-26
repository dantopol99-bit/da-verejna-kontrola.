-- 0013: pohled k publikaci nevydá výsledky metodiky, která čeká na zdroj, je neúplná nebo nahrazená (D-053).
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
   AND NOT ind.obsahuje_hodnotici_slova(v.text)
   AND (NOT ind.je_dotacni(v.typ_castky) OR v.stav_dat_k IS NOT NULL)
   AND coalesce(m.parametry ->> 'stav', 'spocteno') NOT IN ('ceka_na_zdroj', 'neuplna_metodika', 'nahrazena');
