-- 0011: oprava bez mazání – logické ukončení entity a evidence náhrady (D-044).
--
-- Když se ukáže, že entita v dnešním poznání neexistuje (např. tok celé zakázky, která je rozdělena
-- na části: nahradí ho toky částí), aktuální verze se uzavře (recorded_to = now()) a nová verze se
-- nevkládá. Řádky zůstávají, dotaz „jak jsme to věděli v čase T“ vrací původní stav. Důvod a náhrada
-- jsou v core.ukonceni_entity (pouze INSERT). Jiná cesta ukončení než core.ukonci_entitu() není.

CREATE TABLE core.ukonceni_entity (
  id          bigserial PRIMARY KEY,
  tabulka     text NOT NULL CHECK (tabulka IN ('zdrojovy_zaznam', 'subjekt', 'tok', 'tok_zdroj', 'castka',
                                                'udalost', 'limit', 'metodika_verze')),
  entita_id   uuid NOT NULL REFERENCES core.entita (id),
  nahrazeno   uuid[] NOT NULL DEFAULT '{}',
  duvod       text NOT NULL CHECK (duvod <> ''),
  beh_id      bigint REFERENCES core.normalizace_beh (id),
  vlozeno     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ukonceni_entity_entita_idx ON core.ukonceni_entity (entita_id);
COMMENT ON TABLE core.ukonceni_entity IS
  'Logicky ukončené entity (uzavřené aktuální verze bez nástupce): důvod a entity, které je nahrazují. Pouze INSERT.';
CREATE TRIGGER ukonceni_entity_jen_insert BEFORE UPDATE OR DELETE ON core.ukonceni_entity
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER ukonceni_entity_bez_truncate BEFORE TRUNCATE ON core.ukonceni_entity
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

CREATE FUNCTION core.ukonci_entitu(p_tabulka regclass, p_klic uuid, p_duvod text,
                                   p_nahrazeno uuid[] DEFAULT '{}', p_beh bigint DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  v_schema text;
  v_tab    text;
  v_pocet  integer;
BEGIN
  SELECT n.nspname, c.relname INTO v_schema, v_tab
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = p_tabulka;
  IF v_schema <> 'core' OR v_tab NOT IN ('zdrojovy_zaznam', 'subjekt', 'tok', 'tok_zdroj', 'castka', 'udalost',
                                         'limit', 'metodika_verze') THEN
    RAISE EXCEPTION 'core.ukonci_entitu: % není bitemporální tabulka entity', p_tabulka USING ERRCODE = 'PV002';
  END IF;
  IF p_duvod IS NULL OR p_duvod = '' THEN
    RAISE EXCEPTION 'core.ukonci_entitu: důvod ukončení je povinný' USING ERRCODE = 'PV002';
  END IF;
  -- uzavření verze hlídá core.bitemporalni_straz (jen now(), ne v transakci vzniku verze)
  EXECUTE format('UPDATE %s SET recorded_to = now() WHERE %I = $1 AND recorded_to = ''infinity''',
                 p_tabulka, v_tab || '_id') USING p_klic;
  GET DIAGNOSTICS v_pocet = ROW_COUNT;
  IF v_pocet > 0 THEN
    INSERT INTO core.ukonceni_entity (tabulka, entita_id, nahrazeno, duvod, beh_id)
    VALUES (v_tab, p_klic, coalesce(p_nahrazeno, '{}'), p_duvod, p_beh);
  END IF;
  RETURN v_pocet;
END $$;
COMMENT ON FUNCTION core.ukonci_entitu(regclass, uuid, text, uuid[], bigint) IS
  'Logické ukončení entity: uzavře aktuální verze (recorded_to = now()), nic nemaže, důvod a náhradu zapíše.';
