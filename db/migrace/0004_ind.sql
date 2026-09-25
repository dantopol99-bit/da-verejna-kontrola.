-- 0004: ind – výsledky indikátorů a souhrny. Pouze INSERT.
-- Podmínky nepublikování jsou vynuceny třikrát: strukturou tabulek (NOT NULL, jeden typ částky),
-- pohledy *_k_publikaci a publikační bránou v Pythonu (pvk.publikace), kterou hlídají testy.

-- Hodnotící slova ve výstupních textech. Vzory odpovídají pvk.publikace.HODNOTICI_VZORY
-- (malá písmena, tvary s diakritikou i bez ní; podstatná jména "napojení na" / "propojení s"
-- nejsou hodnotící). Shodu obou implementací hlídá test test_sql_a_python_vzory_se_shoduji.
CREATE FUNCTION ind.obsahuje_hodnotici_slova(t text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN t IS NULL THEN false ELSE
    lower(normalize(t, NFC))
      ~ '(\mpodez[řr]|\mrizikov\w*\s+dodavatel|\mpropojen(?!í)\w*\s+se?\M|\mnapojen(?!í)\w*\s+na\M)'
  END
$$;

CREATE TABLE ind.indikator_vysledek (
  id                  bigserial PRIMARY KEY,
  indikator_kod       text NOT NULL CHECK (indikator_kod ~ '^[a-z0-9_]+$'),
  subjekt_id          uuid REFERENCES core.entita (id),
  obdobi_od           date NOT NULL,
  obdobi_do           date NOT NULL,
  pocet_pripadu       integer NOT NULL CHECK (pocet_pripadu >= 0),
  zaklad              numeric,
  hodnota             numeric,
  typ_castky          core.typ_castky,
  podil_heuristiky    numeric(5, 4) CHECK (podil_heuristiky >= 0 AND podil_heuristiky <= 1),
  metodika_verze_id   uuid NOT NULL REFERENCES core.entita (id),
  text                text,
  vypocteno           timestamptz NOT NULL DEFAULT now(),
  CHECK (obdobi_od < obdobi_do)
);
COMMENT ON TABLE ind.indikator_vysledek IS
  'Výsledek indikátoru = signál k prověření, nikdy zjištění. Období, počet případů a verze metodiky jsou povinné.';

CREATE TABLE ind.souhrn (
  id                              bigserial PRIMARY KEY,
  kod                             text NOT NULL CHECK (kod ~ '^[a-z0-9_]+$'),
  subjekt_id                      uuid REFERENCES core.entita (id),
  obdobi_od                       date NOT NULL,
  obdobi_do                       date NOT NULL,
  castka                          core.typovana_castka NOT NULL,
  pocet_castek                    integer NOT NULL CHECK (pocet_castek > 0),
  podil_heuristicke_deduplikace   numeric(5, 4) NOT NULL
                                  CHECK (podil_heuristicke_deduplikace >= 0 AND podil_heuristicke_deduplikace <= 1),
  metodika_verze_id               uuid NOT NULL REFERENCES core.entita (id),
  vypocteno                       timestamptz NOT NULL DEFAULT now(),
  CHECK (obdobi_od < obdobi_do),
  CHECK ((castka).typ IS NOT NULL AND (castka).mena IS NOT NULL AND (castka).dph_rezim IS NOT NULL
         AND (castka).perioda IS NOT NULL AND (castka).hodnota IS NOT NULL)
);
COMMENT ON TABLE ind.souhrn IS
  'Souhrn částek: vždy právě jeden typ částky (výsledek core.soucet) a povinný podíl objemu, '
  'který stojí na heuristické deduplikaci/párování.';

CREATE TRIGGER indikator_vysledek_jen_insert BEFORE UPDATE OR DELETE ON ind.indikator_vysledek
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER indikator_vysledek_bez_truncate BEFORE TRUNCATE ON ind.indikator_vysledek
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER souhrn_jen_insert BEFORE UPDATE OR DELETE ON ind.souhrn
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER souhrn_bez_truncate BEFORE TRUNCATE ON ind.souhrn
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

-- Co smí ven: jen výsledky splňující podmínky publikace podle platné verze metodiky.
CREATE VIEW ind.indikator_k_publikaci AS
SELECT v.*
  FROM ind.indikator_vysledek v
  JOIN core.metodika_verze m
    ON m.metodika_verze_id = v.metodika_verze_id
   AND m.recorded_to = 'infinity'
   AND daterange(m.valid_from, m.valid_to) @> v.vypocteno::date
 WHERE m.parametry ? 'min_pocet_pripadu'
   AND v.pocet_pripadu >= (m.parametry ->> 'min_pocet_pripadu')::int
   AND (v.zaklad IS NULL OR NOT m.parametry ? 'min_zaklad' OR v.zaklad >= (m.parametry ->> 'min_zaklad')::numeric)
   AND NOT ind.obsahuje_hodnotici_slova(v.text);

CREATE VIEW ind.souhrn_k_publikaci AS
SELECT s.*
  FROM ind.souhrn s
  JOIN core.metodika_verze m
    ON m.metodika_verze_id = s.metodika_verze_id
   AND m.recorded_to = 'infinity'
   AND daterange(m.valid_from, m.valid_to) @> s.vypocteno::date;
