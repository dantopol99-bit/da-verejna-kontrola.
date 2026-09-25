-- 0002: raw – neměnná vrstva zdrojových dat.

CREATE TABLE raw.zdroj (
  kod       text PRIMARY KEY CHECK (kod ~ '^[a-z0-9_]+$'),
  nazev     text NOT NULL,
  spravce   text NOT NULL,
  url       text NOT NULL,
  licence   text,
  poznamka  text,
  vlozeno   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE raw.zdroj IS 'Evidence zdrojů dat (registr smluv, VVZ, ReD, ...). Pouze INSERT.';

-- Každý pokus o stažení (včetně neúspěšných) – evidence původu a dostupnosti.
CREATE TABLE raw.stazeni (
  id            bigserial PRIMARY KEY,
  zdroj         text NOT NULL REFERENCES raw.zdroj (kod),
  url           text NOT NULL CHECK (url <> ''),
  metoda        text NOT NULL DEFAULT 'GET' CHECK (metoda IN ('GET', 'POST', 'HEAD')),
  parametry     jsonb,
  cas_stazeni   timestamptz NOT NULL,
  http_status   integer,
  sha256        char(64) CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  velikost      bigint CHECK (velikost >= 0),
  soubor        text,
  content_type  text,
  chyba         text,
  vlozeno       timestamptz NOT NULL DEFAULT now(),
  CHECK ((sha256 IS NULL) = (velikost IS NULL)),
  CHECK (http_status IS NOT NULL OR chyba IS NOT NULL)
);
CREATE INDEX stazeni_zdroj_url_idx ON raw.stazeni (zdroj, url);
COMMENT ON TABLE raw.stazeni IS
  'Log stažení: URL, čas, HTTP status, SHA-256 a velikost obsahu, cesta v obsahově adresovaném úložišti. Pouze INSERT.';

-- Zdrojový záznam (smlouva, oznámení, příjemce, příloha...). Pouze INSERT.
CREATE TABLE raw.zaznam (
  id            bigserial PRIMARY KEY,
  zdroj         text NOT NULL REFERENCES raw.zdroj (kod),
  id_ve_zdroji  text NOT NULL CHECK (id_ve_zdroji <> ''),
  url           text NOT NULL CHECK (url <> ''),
  cas_stazeni   timestamptz NOT NULL,
  hash          char(64) NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
  stazeni_id    bigint REFERENCES raw.stazeni (id),
  format        text NOT NULL CHECK (format IN ('json', 'xml', 'csv', 'html', 'xlsx', 'text', 'binarni')),
  obsah         jsonb NOT NULL,
  redigovano    text[] NOT NULL DEFAULT '{}',
  vlozeno       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (zdroj, id_ve_zdroji, hash)
);
CREATE INDEX zaznam_zdroj_id_idx ON raw.zaznam (zdroj, id_ve_zdroji);
COMMENT ON TABLE raw.zaznam IS
  'Zdrojový záznam tak, jak přišel. hash = SHA-256 kanonické podoby původního záznamu (před případnou '
  'minimalizací osobních údajů, viz redigovano). Stejný záznam se stejným hashem se neukládá dvakrát; '
  'změna ve zdroji = nový řádek. Pouze INSERT.';
COMMENT ON COLUMN raw.zaznam.url IS 'Soubor/URL, ze kterého záznam pochází.';
COMMENT ON COLUMN raw.zaznam.redigovano IS
  'Pole vynechaná z obsah kvůli minimalizaci osobních údajů (fyzické osoby bez IČO). Hash je z původního záznamu.';

CREATE TRIGGER zdroj_jen_insert BEFORE UPDATE OR DELETE ON raw.zdroj
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER zdroj_bez_truncate BEFORE TRUNCATE ON raw.zdroj
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER stazeni_jen_insert BEFORE UPDATE OR DELETE ON raw.stazeni
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER stazeni_bez_truncate BEFORE TRUNCATE ON raw.stazeni
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER zaznam_jen_insert BEFORE UPDATE OR DELETE ON raw.zaznam
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER zaznam_bez_truncate BEFORE TRUNCATE ON raw.zaznam
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
