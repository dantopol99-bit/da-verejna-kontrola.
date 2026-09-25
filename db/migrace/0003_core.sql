-- 0003: core – bitemporální model entit podle metodiky.
--
-- Každá tabulka entity má:
--   verze_id                 technický klíč verze (řádku)
--   <entita>_id              stabilní klíč entity (core.entita)
--   valid_from / valid_to    platnost ve světě, [od, do), 'infinity' = trvá
--   recorded_from / recorded_to  kdy jsme to věděli, [od, do); přiděluje databáze (now())
-- Pravidla (vynucuje trigger core.bitemporalni_straz):
--   * řádek se nikdy nepřepisuje ani nemaže; jediná povolená změna je uzavření verze
--     (recorded_to z 'infinity' na now()),
--   * změna = nová verze, vždy přes core.zapis_verzi(),
--   * mezi aktuálními verzemi jedné entity se intervaly platnosti nepřekrývají (EXCLUDE).

------------------------------------------------------------------------------
-- Registr identit entit
------------------------------------------------------------------------------
CREATE TABLE core.entita (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  typ        text NOT NULL CHECK (typ IN ('zdrojovy_zaznam', 'subjekt', 'tok', 'tok_zdroj', 'castka',
                                          'udalost', 'limit', 'metodika_verze')),
  vytvoreno  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, typ)
);
COMMENT ON TABLE core.entita IS 'Stabilní klíče entit core. Pouze INSERT.';
CREATE TRIGGER entita_jen_insert BEFORE UPDATE OR DELETE ON core.entita
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER entita_bez_truncate BEFORE TRUNCATE ON core.entita
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

------------------------------------------------------------------------------
-- Číselníky (výčtové typy)
------------------------------------------------------------------------------
CREATE TYPE core.typ_castky AS ENUM (
  'predpokladana', 'vysoutezena', 'smluvni', 'zmena_dodatkem', 'dotace_priznana', 'dotace_cerpana', 'vratka'
);
COMMENT ON TYPE core.typ_castky IS 'Typ částky. Částky různých typů se nikdy nesčítají.';

CREATE TYPE core.dph_rezim AS ENUM ('bez_dph', 'vcetne_dph', 'mimo_dph', 'neurceno');
COMMENT ON TYPE core.dph_rezim IS
  'bez_dph / vcetne_dph podle zdroje; mimo_dph = plnění mimo DPH (dotace, vratky); neurceno = zdroj režim neuvádí.';

CREATE TYPE core.perioda_castky AS ENUM ('celkem', 'rocni', 'mesicni', 'jednotkova', 'neurcena');
COMMENT ON TYPE core.perioda_castky IS
  'Časový základ částky: celkem za dobu plnění, za rok, za měsíc, jednotková cena, nebo neurčená.';

CREATE TYPE core.stav_vazby AS ENUM ('dolozena', 'pravdepodobna');
CREATE TYPE core.druh_toku AS ENUM ('verejna_zakazka', 'smlouva', 'dotace');
CREATE TYPE core.typ_udalosti AS ENUM (
  'zahajeni_rizeni', 'zadani_zakazky', 'uzavreni_smlouvy', 'zverejneni', 'dodatek',
  'rozhodnuti_o_dotaci', 'platba', 'vratka', 'ukonceni', 'zneplatneni'
);

------------------------------------------------------------------------------
-- Pomocné funkce
------------------------------------------------------------------------------
CREATE FUNCTION core.ico_platne(ico text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT CASE WHEN ico ~ '^[0-9]{8}$' THEN
    (11 - ((substr(ico, 1, 1)::int * 8 + substr(ico, 2, 1)::int * 7 + substr(ico, 3, 1)::int * 6
          + substr(ico, 4, 1)::int * 5 + substr(ico, 5, 1)::int * 4 + substr(ico, 6, 1)::int * 3
          + substr(ico, 7, 1)::int * 2) % 11)) % 10 = substr(ico, 8, 1)::int
  ELSE false END
$$;
COMMENT ON FUNCTION core.ico_platne(text) IS 'IČO: 8 číslic a kontrolní číslice (modulo 11).';

-- Strážce bitemporality: INSERT dostane transakční čas, UPDATE smí jen uzavřít verzi, DELETE nikdy.
CREATE FUNCTION core.bitemporalni_straz() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    NEW.recorded_from := now();
    NEW.recorded_to := 'infinity';
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.recorded_to <> 'infinity' THEN
      RAISE EXCEPTION 'core.%: uzavřenou verzi nelze měnit', TG_TABLE_NAME USING ERRCODE = 'PV002';
    END IF;
    -- generované sloupce (entita_typ) jsou v BEFORE triggeru v NEW ještě NULL, proto se neporovnávají
    IF (to_jsonb(NEW) - ARRAY['recorded_to', 'entita_typ'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['recorded_to', 'entita_typ']) THEN
      RAISE EXCEPTION 'core.%: řádek nelze přepsat, změna = nová verze (core.zapis_verzi)', TG_TABLE_NAME
        USING ERRCODE = 'PV002';
    END IF;
    IF NEW.recorded_to IS DISTINCT FROM now() THEN
      RAISE EXCEPTION 'core.%: verzi lze uzavřít jen transakčním časem now()', TG_TABLE_NAME
        USING ERRCODE = 'PV002';
    END IF;
    IF NEW.recorded_to <= OLD.recorded_from THEN
      RAISE EXCEPTION 'core.%: verzi nelze uzavřít ve stejné transakci, ve které vznikla', TG_TABLE_NAME
        USING ERRCODE = 'PV002';
    END IF;
    RETURN NEW;
  ELSE
    RAISE EXCEPTION 'core.%: operace % není povolena (nic se nemaže)', TG_TABLE_NAME, TG_OP
      USING ERRCODE = 'PV002';
  END IF;
END $$;

------------------------------------------------------------------------------
-- Entity
------------------------------------------------------------------------------

-- Verze metodiky: parametry výpočtů (tolerance, prahy, minimální základy).
CREATE TABLE core.metodika_verze (
  verze_id           bigserial PRIMARY KEY,
  metodika_verze_id  uuid NOT NULL,
  entita_typ         text GENERATED ALWAYS AS ('metodika_verze') STORED,
  kod                text NOT NULL CHECK (kod ~ '^[a-z0-9._-]+$'),
  popis              text NOT NULL,
  parametry          jsonb NOT NULL CHECK (jsonb_typeof(parametry) = 'object'),
  dokument           text,
  dokument_sha256    char(64) CHECK (dokument_sha256 ~ '^[0-9a-f]{64}$'),
  valid_from         date NOT NULL,
  valid_to           date NOT NULL DEFAULT 'infinity',
  recorded_from      timestamptz NOT NULL DEFAULT now(),
  recorded_to        timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (metodika_verze_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (metodika_verze_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);
CREATE UNIQUE INDEX metodika_verze_kod_aktualni ON core.metodika_verze (kod)
  WHERE recorded_to = 'infinity' AND valid_to = 'infinity';

-- Limity: zákonné (hranice zveřejnění, limity VZ) i metodické (minimální základ indikátoru).
CREATE TABLE core.limit (
  verze_id       bigserial PRIMARY KEY,
  limit_id       uuid NOT NULL,
  entita_typ     text GENERATED ALWAYS AS ('limit') STORED,
  kod            text NOT NULL CHECK (kod ~ '^[a-z0-9_]+$'),
  popis          text NOT NULL,
  hodnota        numeric NOT NULL,
  jednotka       text NOT NULL,
  dph_rezim      core.dph_rezim,
  pravni_zaklad  text NOT NULL,
  valid_from     date NOT NULL,
  valid_to       date NOT NULL DEFAULT 'infinity',
  recorded_from  timestamptz NOT NULL DEFAULT now(),
  recorded_to    timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (limit_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (limit_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Zdrojový záznam: most mezi core a raw (smlouva v RS, oznámení ve VVZ, rozhodnutí o dotaci...).
CREATE TABLE core.zdrojovy_zaznam (
  verze_id            bigserial PRIMARY KEY,
  zdrojovy_zaznam_id  uuid NOT NULL,
  entita_typ          text GENERATED ALWAYS AS ('zdrojovy_zaznam') STORED,
  raw_zaznam_id       bigint NOT NULL REFERENCES raw.zaznam (id),
  zdroj               text NOT NULL REFERENCES raw.zdroj (kod),
  id_ve_zdroji        text NOT NULL,
  druh                text NOT NULL CHECK (druh IN ('smlouva', 'zakazka', 'dotace', 'operace_eu', 'prijemce', 'priloha')),
  url                 text NOT NULL,
  valid_from          date NOT NULL,
  valid_to            date NOT NULL DEFAULT 'infinity',
  recorded_from       timestamptz NOT NULL DEFAULT now(),
  recorded_to         timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (zdrojovy_zaznam_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (zdrojovy_zaznam_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Subjekt: jen odkaz na IČO. Název, sídlo, vlastnictví drží kotva (Firemní databáze).
CREATE TABLE core.subjekt (
  verze_id       bigserial PRIMARY KEY,
  subjekt_id     uuid NOT NULL,
  entita_typ     text GENERATED ALWAYS AS ('subjekt') STORED,
  ico            char(8) NOT NULL CHECK (core.ico_platne(ico)),
  valid_from     date NOT NULL,
  valid_to       date NOT NULL DEFAULT 'infinity',
  recorded_from  timestamptz NOT NULL DEFAULT now(),
  recorded_to    timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (subjekt_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (subjekt_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity'),
  EXCLUDE USING gist (ico WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);
COMMENT ON TABLE core.subjekt IS
  'Odkaz na subjekt kotvy přes IČO. Žádné názvy ani adresy – ty se berou z kotvy v okamžiku dotazu.';

-- Tok veřejných peněz: plátce -> příjemce, doložený jedním či více zdrojovými záznamy.
CREATE TABLE core.tok (
  verze_id                bigserial PRIMARY KEY,
  tok_id                  uuid NOT NULL,
  entita_typ              text GENERATED ALWAYS AS ('tok') STORED,
  druh                    core.druh_toku NOT NULL,
  platce_subjekt_id       uuid REFERENCES core.entita (id),
  prijemce_subjekt_id     uuid REFERENCES core.entita (id),
  subjekt_neurcen_duvod   text,
  predmet                 text,
  valid_from              date NOT NULL,
  valid_to                date NOT NULL DEFAULT 'infinity',
  recorded_from           timestamptz NOT NULL DEFAULT now(),
  recorded_to             timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (tok_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK ((platce_subjekt_id IS NOT NULL AND prijemce_subjekt_id IS NOT NULL) OR subjekt_neurcen_duvod IS NOT NULL),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (tok_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Vazba toku na zdrojový záznam: doložená (identifikátor ve zdroji) nebo pravděpodobná (heuristika).
CREATE TABLE core.tok_zdroj (
  verze_id             bigserial PRIMARY KEY,
  tok_zdroj_id         uuid NOT NULL,
  entita_typ           text GENERATED ALWAYS AS ('tok_zdroj') STORED,
  tok_id               uuid NOT NULL REFERENCES core.entita (id),
  zdrojovy_zaznam_id   uuid NOT NULL REFERENCES core.entita (id),
  stav                 core.stav_vazby NOT NULL,
  metoda               text NOT NULL CHECK (metoda ~ '^[a-z0-9_]+$'),
  skore                numeric(4, 3) NOT NULL CHECK (skore >= 0 AND skore <= 1),
  metodika_verze_id    uuid NOT NULL REFERENCES core.entita (id),
  zduvodneni           text,
  valid_from           date NOT NULL,
  valid_to             date NOT NULL DEFAULT 'infinity',
  recorded_from        timestamptz NOT NULL DEFAULT now(),
  recorded_to          timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (tok_zdroj_id, entita_typ) REFERENCES core.entita (id, typ),
  -- skóre 1 je vyhrazeno doloženým vazbám; heuristika nikdy nedosáhne jistoty
  CHECK ((stav = 'dolozena') = (skore = 1)),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (tok_zdroj_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Částka: vždy typ, měna, režim DPH a perioda.
CREATE TABLE core.castka (
  verze_id             bigserial PRIMARY KEY,
  castka_id            uuid NOT NULL,
  entita_typ           text GENERATED ALWAYS AS ('castka') STORED,
  tok_id               uuid REFERENCES core.entita (id),
  zdrojovy_zaznam_id   uuid NOT NULL REFERENCES core.entita (id),
  typ                  core.typ_castky NOT NULL,
  hodnota              numeric(18, 2) NOT NULL,
  mena                 char(3) NOT NULL CHECK (mena ~ '^[A-Z]{3}$'),
  dph_rezim            core.dph_rezim NOT NULL,
  perioda              core.perioda_castky NOT NULL,
  obdobi_od            date,
  obdobi_do            date,
  valid_from           date NOT NULL,
  valid_to             date NOT NULL DEFAULT 'infinity',
  recorded_from        timestamptz NOT NULL DEFAULT now(),
  recorded_to          timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (castka_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (obdobi_od IS NULL OR obdobi_do IS NULL OR obdobi_od < obdobi_do),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (castka_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Událost: uzavření smlouvy, dodatek, rozhodnutí o dotaci, platba, vratka...
CREATE TABLE core.udalost (
  verze_id             bigserial PRIMARY KEY,
  udalost_id           uuid NOT NULL,
  entita_typ           text GENERATED ALWAYS AS ('udalost') STORED,
  tok_id               uuid REFERENCES core.entita (id),
  zdrojovy_zaznam_id   uuid NOT NULL REFERENCES core.entita (id),
  typ                  core.typ_udalosti NOT NULL,
  datum                date NOT NULL,
  popis                text,
  valid_from           date NOT NULL,
  valid_to             date NOT NULL DEFAULT 'infinity',
  recorded_from        timestamptz NOT NULL DEFAULT now(),
  recorded_to          timestamptz NOT NULL DEFAULT 'infinity',
  FOREIGN KEY (udalost_id, entita_typ) REFERENCES core.entita (id, typ),
  CHECK (valid_from < valid_to),
  CHECK (recorded_from < recorded_to),
  EXCLUDE USING gist (udalost_id WITH =, daterange(valid_from, valid_to) WITH &&)
    WHERE (recorded_to = 'infinity')
);

-- Strážci bitemporality na všech tabulkách entit.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['metodika_verze', 'limit', 'zdrojovy_zaznam', 'subjekt', 'tok', 'tok_zdroj',
                           'castka', 'udalost']
  LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON core.%I '
                   'FOR EACH ROW EXECUTE FUNCTION core.bitemporalni_straz()', t || '_straz', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON core.%I '
                   'FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert()', t || '_bez_truncate', t);
    EXECUTE format('CREATE VIEW core.%I AS SELECT * FROM core.%I WHERE recorded_to = ''infinity''',
                   t || '_aktualni', t);
  END LOOP;
END $$;

------------------------------------------------------------------------------
-- Zápis nové verze (jediná cesta, jak v core něco změnit)
------------------------------------------------------------------------------
-- p_tabulka  tabulka entity v core (např. 'core.tok')
-- p_data     atributy jako jsonb; obsahuje-li klíč <entita>_id, zapisuje se nová verze existující
--            entity, jinak se založí nová entita
-- p_valid_from, p_valid_to  interval platnosti nové verze [od, do)
-- Postup (klasická bitemporální aktualizace):
--   1. aktuální verze překrývající nový interval se uzavřou (recorded_to = now()),
--   2. jejich části mimo nový interval se znovu vloží beze změny,
--   3. vloží se nová verze.
-- Pokud už existuje identická aktuální verze se stejným intervalem, nic se nezapíše (idempotence).
CREATE FUNCTION core.zapis_verzi(p_tabulka regclass, p_data jsonb, p_valid_from date,
                                 p_valid_to date DEFAULT 'infinity')
RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
  v_schema   text;
  v_tab      text;
  v_klic_sl  text;
  v_klic     uuid;
  v_sloupce  text;
  v_data     jsonb;
  v_vyjmout  text[] := ARRAY['verze_id', 'entita_typ', 'valid_from', 'valid_to', 'recorded_from', 'recorded_to'];
  v_shoda    boolean;
  r          record;
BEGIN
  SELECT n.nspname, c.relname INTO v_schema, v_tab
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = p_tabulka;
  IF v_schema <> 'core' OR v_tab = 'entita' THEN
    RAISE EXCEPTION 'core.zapis_verzi: % není bitemporální tabulka entity', p_tabulka USING ERRCODE = 'PV002';
  END IF;
  IF p_valid_from IS NULL OR p_valid_to IS NULL OR p_valid_from >= p_valid_to THEN
    RAISE EXCEPTION 'core.zapis_verzi: neplatný interval platnosti [%, %)', p_valid_from, p_valid_to
      USING ERRCODE = 'PV002';
  END IF;

  v_klic_sl := v_tab || '_id';
  v_klic := (p_data ->> v_klic_sl)::uuid;
  IF v_klic IS NULL THEN
    INSERT INTO core.entita (typ) VALUES (v_tab) RETURNING id INTO v_klic;
  END IF;
  v_data := p_data || jsonb_build_object(v_klic_sl, v_klic);

  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO v_sloupce
    FROM pg_attribute
   WHERE attrelid = p_tabulka AND attnum > 0 AND NOT attisdropped AND attgenerated = ''
     AND attname <> ALL (v_vyjmout);

  -- idempotence: identická aktuální verze se stejným intervalem už existuje
  EXECUTE format(
    'SELECT EXISTS (SELECT 1 FROM %1$s t WHERE %2$I = $1 AND recorded_to = ''infinity'' '
    'AND valid_from = $2 AND valid_to = $3 '
    'AND (to_jsonb(t) - $4) = (to_jsonb(jsonb_populate_record(NULL::%1$s, $5)) - $4))',
    p_tabulka, v_klic_sl)
    INTO v_shoda USING v_klic, p_valid_from, p_valid_to, v_vyjmout, v_data;
  IF v_shoda THEN
    RETURN v_klic;
  END IF;

  FOR r IN EXECUTE format(
      'SELECT verze_id, valid_from, valid_to FROM %1$s WHERE %2$I = $1 AND recorded_to = ''infinity'' '
      'AND daterange(valid_from, valid_to) && daterange($2, $3) ORDER BY valid_from FOR UPDATE',
      p_tabulka, v_klic_sl)
    USING v_klic, p_valid_from, p_valid_to
  LOOP
    EXECUTE format('UPDATE %s SET recorded_to = now() WHERE verze_id = $1', p_tabulka) USING r.verze_id;
    IF r.valid_from < p_valid_from THEN
      EXECUTE format('INSERT INTO %1$s (%2$s, valid_from, valid_to) '
                     'SELECT %2$s, valid_from, $2 FROM %1$s WHERE verze_id = $1', p_tabulka, v_sloupce)
        USING r.verze_id, p_valid_from;
    END IF;
    IF r.valid_to > p_valid_to THEN
      EXECUTE format('INSERT INTO %1$s (%2$s, valid_from, valid_to) '
                     'SELECT %2$s, $2, valid_to FROM %1$s WHERE verze_id = $1', p_tabulka, v_sloupce)
        USING r.verze_id, p_valid_to;
    END IF;
  END LOOP;

  EXECUTE format('INSERT INTO %1$s (%2$s, valid_from, valid_to) '
                 'SELECT %2$s, $2, $3 FROM jsonb_populate_record(NULL::%1$s, $1)', p_tabulka, v_sloupce)
    USING v_data, p_valid_from, p_valid_to;
  RETURN v_klic;
END $$;

COMMENT ON FUNCTION core.zapis_verzi(regclass, jsonb, date, date) IS
  'Jediná cesta změny v core: uzavře překrývající se aktuální verze, zachová jejich zbytky a vloží novou verzi.';

------------------------------------------------------------------------------
-- Typovaná částka: sčítání napříč typy je technicky znemožněno
------------------------------------------------------------------------------
-- Pro core.typovana_castka neexistuje operátor + ani agregát sum(); jediný součet je core.soucet(),
-- který vyžaduje shodu typu, měny, režimu DPH i periody, jinak skončí chybou PV003.
CREATE TYPE core.typovana_castka AS (
  typ        core.typ_castky,
  mena       char(3),
  dph_rezim  core.dph_rezim,
  perioda    core.perioda_castky,
  hodnota    numeric
);

CREATE FUNCTION core.typovana_castka_pricti(stav core.typovana_castka, dalsi core.typovana_castka)
RETURNS core.typovana_castka
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF dalsi IS NULL THEN
    RETURN stav;
  END IF;
  IF dalsi.typ IS NULL OR dalsi.mena IS NULL OR dalsi.dph_rezim IS NULL OR dalsi.perioda IS NULL
     OR dalsi.hodnota IS NULL THEN
    RAISE EXCEPTION 'částku bez typu, měny, režimu DPH, periody nebo hodnoty nelze sčítat'
      USING ERRCODE = 'PV003';
  END IF;
  IF stav IS NULL THEN
    RETURN dalsi;
  END IF;
  IF (stav.typ, stav.mena, stav.dph_rezim, stav.perioda)
     IS DISTINCT FROM (dalsi.typ, dalsi.mena, dalsi.dph_rezim, dalsi.perioda) THEN
    RAISE EXCEPTION 'sčítání částek různých typů není povoleno: (%, %, %, %) + (%, %, %, %)',
      stav.typ, stav.mena, stav.dph_rezim, stav.perioda, dalsi.typ, dalsi.mena, dalsi.dph_rezim, dalsi.perioda
      USING ERRCODE = 'PV003';
  END IF;
  RETURN ROW(stav.typ, stav.mena, stav.dph_rezim, stav.perioda, stav.hodnota + dalsi.hodnota)::core.typovana_castka;
END $$;

CREATE AGGREGATE core.soucet(core.typovana_castka) (
  SFUNC = core.typovana_castka_pricti,
  STYPE = core.typovana_castka
);
COMMENT ON AGGREGATE core.soucet(core.typovana_castka) IS
  'Jediný povolený součet částek. Různé typy / měny / režimy DPH / periody -> chyba PV003.';

CREATE VIEW core.castka_typovana AS
SELECT castka_id, tok_id, zdrojovy_zaznam_id, obdobi_od, obdobi_do, valid_from, valid_to,
       ROW(typ, mena, dph_rezim, perioda, hodnota)::core.typovana_castka AS castka
  FROM core.castka
 WHERE recorded_to = 'infinity';
