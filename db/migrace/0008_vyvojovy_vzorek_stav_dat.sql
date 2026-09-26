-- 0008: vývojový vzorek v raw (D-040) a stav dat k datu u výsledků (D-039).
--
-- 1. raw.zaznam.vyvojovy_vzorek: záznam slouží jen k vývoji (normalizace, testy nad reálnými daty),
--    nikdy jako zdroj publikovaných dat. Zrcadlo registru smluv (Hlídač státu) smí do raw jen s tímto
--    příznakem; omezení je NOT VALID, aby platilo pro nové řádky a nedotklo se záznamů pilotu
--    v existujících databázích (raw je pouze INSERT, starý řádek nelze přeznačit).
-- 2. ind.*.stav_dat_k: datum stavu dat zdroje (u IS ReD datum exportu). Dotační výsledek bez něj
--    pohled k publikaci nevydá (D-039: chybějící dotace není žádná dotace, číslo nese stav k datu).

ALTER TABLE raw.zaznam ADD COLUMN vyvojovy_vzorek boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN raw.zaznam.vyvojovy_vzorek IS
  'Vývojový vzorek (D-040): záznam se smí použít jen při vývoji, nikdy jako zdroj publikovaných dat.';
ALTER TABLE raw.zaznam ADD CONSTRAINT zaznam_zrcadlo_jen_vyvojovy_vzorek
  CHECK (zdroj <> 'hlidac_statu_rs' OR vyvojovy_vzorek) NOT VALID;
CREATE INDEX zaznam_vyvojovy_vzorek_idx ON raw.zaznam (zdroj) WHERE vyvojovy_vzorek;

ALTER TABLE ind.indikator_vysledek ADD COLUMN stav_dat_k date;
ALTER TABLE ind.souhrn ADD COLUMN stav_dat_k date;
COMMENT ON COLUMN ind.indikator_vysledek.stav_dat_k IS
  'Stav dat zdroje k datu (u IS ReD datum exportu). Povinný pro dotační výsledky (D-039).';
COMMENT ON COLUMN ind.souhrn.stav_dat_k IS
  'Stav dat zdroje k datu (u IS ReD datum exportu). Povinný pro dotační souhrny (D-039).';

-- Dotační údaj = typ částky dotace_priznana, dotace_cerpana nebo vratka.
CREATE FUNCTION ind.je_dotacni(t core.typ_castky) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT t IS NOT NULL AND t IN ('dotace_priznana', 'dotace_cerpana', 'vratka')
$$;

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
   AND (NOT ind.je_dotacni(v.typ_castky) OR v.stav_dat_k IS NOT NULL);

CREATE OR REPLACE VIEW ind.souhrn_k_publikaci AS
SELECT s.*
  FROM ind.souhrn s
  JOIN core.metodika_verze m
    ON m.metodika_verze_id = s.metodika_verze_id
   AND m.recorded_to = 'infinity'
   AND daterange(m.valid_from, m.valid_to) @> s.vypocteno::date
 WHERE NOT ind.je_dotacni((s.castka).typ) OR s.stav_dat_k IS NOT NULL;
