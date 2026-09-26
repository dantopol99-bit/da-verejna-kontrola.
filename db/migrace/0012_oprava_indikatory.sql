-- 0012: obecná oprava formou nové verze (D-048) a povinné údaje výsledků indikátorů (D-050).
--
-- 1. core.oprav_entitu(): uzavře VŠECHNY aktuální verze entity (i s jiným intervalem platnosti) a vloží
--    opravené verze s novými intervaly. Nic nemaže; původní a opravený stav a důvod jsou v core.oprava.
--    Na rozdíl od core.zapis_verzi() umí změnit i začátek platnosti (zapis_verzi zachová zbytek starého
--    intervalu před novým začátkem).
-- 2. core.oprav_zaznam(): oprava údaje v evidenci, která je pouze INSERT (např. core.ukonceni_entity):
--    původní řádek zůstává, opravená hodnota je v core.oprava; pohled core.ukonceni_entity_opravene ji uplatní.
-- 3. ind.indikator_vysledek.srovnavaci_skupina: každý nový výsledek nese srovnávací skupinu a základ.

CREATE TABLE core.oprava (
  id          bigserial PRIMARY KEY,
  tabulka     text NOT NULL,
  entita_id   uuid REFERENCES core.entita (id),
  zaznam_id   bigint,
  pole        text,
  puvodni     jsonb NOT NULL,
  opraveno    jsonb NOT NULL,
  duvod       text NOT NULL CHECK (duvod <> ''),
  vlozeno     timestamptz NOT NULL DEFAULT now(),
  CHECK ((entita_id IS NULL) <> (zaznam_id IS NULL))
);
CREATE INDEX oprava_entita_idx ON core.oprava (entita_id);
CREATE INDEX oprava_zaznam_idx ON core.oprava (tabulka, zaznam_id);
COMMENT ON TABLE core.oprava IS
  'Opravy formou nové verze: původní a opravený stav, důvod. Pouze INSERT (D-048).';
CREATE TRIGGER oprava_jen_insert BEFORE UPDATE OR DELETE ON core.oprava
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER oprava_bez_truncate BEFORE TRUNCATE ON core.oprava
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

-- p_verze: [{"data": {atributy bez klíče entity}, "valid_from": "RRRR-MM-DD", "valid_to": "RRRR-MM-DD" | null}]
CREATE FUNCTION core.oprav_entitu(p_tabulka regclass, p_klic uuid, p_verze jsonb, p_duvod text)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  v_schema   text;
  v_tab      text;
  v_klic_sl  text;
  v_sloupce  text;
  v_vyjmout  text[] := ARRAY['verze_id', 'entita_typ', 'recorded_from', 'recorded_to'];
  v_puvodni  jsonb;
  v_nove     jsonb;
  v          jsonb;
BEGIN
  SELECT n.nspname, c.relname INTO v_schema, v_tab
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = p_tabulka;
  IF v_schema <> 'core' OR v_tab NOT IN ('zdrojovy_zaznam', 'subjekt', 'tok', 'tok_zdroj', 'castka', 'udalost',
                                         'limit', 'metodika_verze') THEN
    RAISE EXCEPTION 'core.oprav_entitu: % není bitemporální tabulka entity', p_tabulka USING ERRCODE = 'PV002';
  END IF;
  IF p_duvod IS NULL OR p_duvod = '' THEN
    RAISE EXCEPTION 'core.oprav_entitu: důvod opravy je povinný' USING ERRCODE = 'PV002';
  END IF;
  IF jsonb_typeof(p_verze) <> 'array' OR jsonb_array_length(p_verze) = 0 THEN
    RAISE EXCEPTION 'core.oprav_entitu: chybí opravené verze (k ukončení entity slouží core.ukonci_entitu)'
      USING ERRCODE = 'PV002';
  END IF;
  v_klic_sl := v_tab || '_id';
  SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO v_sloupce
    FROM pg_attribute
   WHERE attrelid = p_tabulka AND attnum > 0 AND NOT attisdropped AND attgenerated = ''
     AND attname <> ALL (v_vyjmout || ARRAY['valid_from', 'valid_to']);

  EXECUTE format('SELECT jsonb_agg(to_jsonb(t) - $2 ORDER BY t.valid_from) FROM %s t '
                 'WHERE %I = $1 AND recorded_to = ''infinity''', p_tabulka, v_klic_sl)
    INTO v_puvodni USING p_klic, v_vyjmout;
  IF v_puvodni IS NULL THEN
    RAISE EXCEPTION 'core.oprav_entitu: entita % nemá aktuální verzi', p_klic USING ERRCODE = 'PV002';
  END IF;
  -- požadovaný stav ve stejné podobě jako aktuální verze (idempotence: stejný stav = nic nedělat)
  EXECUTE format('SELECT jsonb_agg(to_jsonb(jsonb_populate_record(NULL::%1$s, (x->''data'') || jsonb_build_object(%2$L, $1)'
                 ' || jsonb_build_object(''valid_from'', x->>''valid_from'', ''valid_to'', coalesce(x->>''valid_to'', ''infinity'')))) - $3'
                 ' ORDER BY (x->>''valid_from'')::date) FROM jsonb_array_elements($2) x', p_tabulka, v_klic_sl)
    INTO v_nove USING p_klic, p_verze, v_vyjmout;
  IF v_nove = v_puvodni THEN
    RETURN 0;
  END IF;

  EXECUTE format('UPDATE %s SET recorded_to = now() WHERE %I = $1 AND recorded_to = ''infinity''', p_tabulka, v_klic_sl)
    USING p_klic;
  FOR v IN SELECT * FROM jsonb_array_elements(p_verze) LOOP
    EXECUTE format('INSERT INTO %1$s (%2$s, valid_from, valid_to) '
                   'SELECT %2$s, $2, $3 FROM jsonb_populate_record(NULL::%1$s, $1)', p_tabulka, v_sloupce)
      USING (v -> 'data') || jsonb_build_object(v_klic_sl, p_klic), (v ->> 'valid_from')::date,
            coalesce((v ->> 'valid_to')::date, 'infinity'::date);
  END LOOP;
  INSERT INTO core.oprava (tabulka, entita_id, puvodni, opraveno, duvod) VALUES (v_tab, p_klic, v_puvodni, v_nove, p_duvod);
  RETURN jsonb_array_length(p_verze);
END $$;
COMMENT ON FUNCTION core.oprav_entitu(regclass, uuid, jsonb, text) IS
  'Oprava novou verzí včetně změny intervalu platnosti: uzavře všechny aktuální verze, vloží opravené, zapíše důvod.';

CREATE FUNCTION core.oprav_zaznam(p_tabulka text, p_id bigint, p_pole text, p_hodnota jsonb, p_duvod text)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  v_puvodni jsonb;
BEGIN
  IF p_tabulka NOT IN ('ukonceni_entity', 'normalizace_vyjimka') THEN
    RAISE EXCEPTION 'core.oprav_zaznam: evidence % se neopravuje', p_tabulka USING ERRCODE = 'PV002';
  END IF;
  IF p_duvod IS NULL OR p_duvod = '' THEN
    RAISE EXCEPTION 'core.oprav_zaznam: důvod opravy je povinný' USING ERRCODE = 'PV002';
  END IF;
  EXECUTE format('SELECT to_jsonb(t) -> $2 FROM core.%I t WHERE id = $1', p_tabulka) INTO v_puvodni USING p_id, p_pole;
  IF v_puvodni IS NULL THEN
    RAISE EXCEPTION 'core.oprav_zaznam: záznam %.% nebo pole % neexistuje', p_tabulka, p_id, p_pole USING ERRCODE = 'PV002';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM core.oprava WHERE tabulka = p_tabulka AND zaznam_id = p_id AND pole = p_pole
                    AND opraveno = p_hodnota) THEN
    INSERT INTO core.oprava (tabulka, zaznam_id, pole, puvodni, opraveno, duvod)
    VALUES (p_tabulka, p_id, p_pole, v_puvodni, p_hodnota, p_duvod);
  END IF;
END $$;

CREATE VIEW core.ukonceni_entity_opravene AS
SELECT u.id, u.tabulka, u.entita_id,
       coalesce((SELECT ARRAY(SELECT jsonb_array_elements_text(o.opraveno))::uuid[] FROM core.oprava o
                  WHERE o.tabulka = 'ukonceni_entity' AND o.zaznam_id = u.id AND o.pole = 'nahrazeno'
                  ORDER BY o.id DESC LIMIT 1), u.nahrazeno) AS nahrazeno,
       u.duvod, u.beh_id, u.vlozeno
  FROM core.ukonceni_entity u;
COMMENT ON VIEW core.ukonceni_entity_opravene IS 'Evidence ukončení s uplatněnými opravami (core.oprava).';

ALTER TABLE ind.indikator_vysledek ADD COLUMN srovnavaci_skupina text;
ALTER TABLE ind.indikator_vysledek ADD CONSTRAINT indikator_zaklad_a_skupina
  CHECK (zaklad IS NOT NULL AND srovnavaci_skupina IS NOT NULL AND srovnavaci_skupina <> '') NOT VALID;
COMMENT ON COLUMN ind.indikator_vysledek.srovnavaci_skupina IS
  'Srovnávací skupina výsledku (velikostní skupina, CPV skupina, druh řízení ...). Povinná pro nové výsledky (D-050).';
