-- 0007: evidence běhů sběru (make sber). Pouze INSERT jako celé schéma raw.
-- Začátek a konec běhu jsou dva řádky ve dvou tabulkách (konec se k začátku nepřepisuje);
-- běh bez řádku v raw.beh_konec je nedokončený (spadl proces). Přehled v pohledu raw.beh_prehled.

CREATE TABLE raw.beh (
  id          bigserial PRIMARY KEY,
  zdroj       text NOT NULL REFERENCES raw.zdroj (kod),
  zacatek     timestamptz NOT NULL DEFAULT clock_timestamp(),
  obdobi_od   date,
  obdobi_do   date,
  parametry   jsonb,
  vlozeno     timestamptz NOT NULL DEFAULT now(),
  CHECK (obdobi_od IS NULL OR obdobi_do IS NULL OR obdobi_od < obdobi_do)
);
COMMENT ON TABLE raw.beh IS 'Začátek běhu stahovače jednoho zdroje (období, parametry). Pouze INSERT.';

CREATE TABLE raw.beh_konec (
  beh_id           bigint PRIMARY KEY REFERENCES raw.beh (id),
  konec            timestamptz NOT NULL DEFAULT clock_timestamp(),
  stav             text NOT NULL CHECK (stav IN ('uspech', 'chyba', 'preskoceno')),
  pocet_zaznamu    integer NOT NULL DEFAULT 0 CHECK (pocet_zaznamu >= 0),
  pocet_novych     integer NOT NULL DEFAULT 0 CHECK (pocet_novych >= 0),
  pocet_ve_zdroji  integer CHECK (pocet_ve_zdroji >= 0),
  chyby            jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(chyby) = 'array'),
  poznamka         text,
  vlozeno          timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE raw.beh_konec IS
  'Konec běhu: stav (uspech | chyba | preskoceno = zdroj nedostupný), počet zpracovaných záznamů, '
  'počet nově vložených do raw.zaznam, počet uváděný zdrojem (pokud ho uvádí) a chyby. Pouze INSERT.';

ALTER TABLE raw.stazeni ADD COLUMN beh_id bigint REFERENCES raw.beh (id);
ALTER TABLE raw.zaznam ADD COLUMN beh_id bigint REFERENCES raw.beh (id);
COMMENT ON COLUMN raw.zaznam.beh_id IS 'Běh sběru, který záznam poprvé vložil (opakovaný běh stejný záznam nevkládá).';
CREATE INDEX zaznam_beh_idx ON raw.zaznam (beh_id);

CREATE TRIGGER beh_jen_insert BEFORE UPDATE OR DELETE ON raw.beh
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER beh_bez_truncate BEFORE TRUNCATE ON raw.beh
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER beh_konec_jen_insert BEFORE UPDATE OR DELETE ON raw.beh_konec
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER beh_konec_bez_truncate BEFORE TRUNCATE ON raw.beh_konec
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

CREATE VIEW raw.beh_prehled AS
SELECT b.id, b.zdroj, b.zacatek, k.konec, coalesce(k.stav, 'nedokonceno') AS stav,
       b.obdobi_od, b.obdobi_do, k.pocet_zaznamu, k.pocet_novych, k.pocet_ve_zdroji,
       coalesce(jsonb_array_length(k.chyby), 0) AS pocet_chyb, k.chyby, k.poznamka, b.parametry
FROM raw.beh b LEFT JOIN raw.beh_konec k ON k.beh_id = b.id;
COMMENT ON VIEW raw.beh_prehled IS 'Přehled běhů sběru (make sber-stav).';
