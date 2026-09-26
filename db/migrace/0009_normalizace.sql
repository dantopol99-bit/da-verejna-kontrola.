-- 0009: normalizace raw -> core (blok 3).
--
-- 1. core.castka: přepočet cizí měny kurzem ČNB k datu uzavření. Původní hodnota a měna zůstávají
--    (hodnota, mena); přepočet je vedle nich (hodnota_czk, kurz_cnb, kurz_datum). Když kurzy ČNB
--    nejsou dostupné, zůstane částka nepřepočtená s příznakem prepocet = 'kurz_nedostupny'.
-- 2. core.castka.stav_dat_k: stav dat zdroje k datu (D-039), u dotačních částek povinný.
-- 3. core.normalizace_beh / core.normalizace_vyjimka: evidence běhů normalizace a výjimek
--    (neplatné IČO, IČO nenalezené v kotvě, chybějící datum ...). Pouze INSERT.
-- 4. core.pokryti_platcu: které zdroje zachycují zadavatele/poskytovatele a od kdy.
-- 5. Typ události 'zruseni' (zrušení zadávacího řízení; zneplatnění formuláře je 'zneplatneni').

ALTER TYPE core.typ_udalosti ADD VALUE IF NOT EXISTS 'zruseni';

ALTER TABLE core.castka ADD COLUMN prepocet text NOT NULL DEFAULT 'neni_treba'
  CHECK (prepocet IN ('neni_treba', 'kurz_cnb', 'kurz_nedostupny'));
ALTER TABLE core.castka ADD COLUMN hodnota_czk numeric(18, 2);
ALTER TABLE core.castka ADD COLUMN kurz_cnb numeric(18, 6) CHECK (kurz_cnb > 0);
ALTER TABLE core.castka ADD COLUMN kurz_datum date;
ALTER TABLE core.castka ADD COLUMN stav_dat_k date;
ALTER TABLE core.castka ADD CONSTRAINT castka_prepocet_konzistentni CHECK (
  (mena = 'CZK') = (prepocet = 'neni_treba')
  AND (prepocet = 'kurz_cnb') = (hodnota_czk IS NOT NULL AND kurz_cnb IS NOT NULL AND kurz_datum IS NOT NULL)
) NOT VALID;
ALTER TABLE core.castka ADD CONSTRAINT castka_dotace_stav_dat_k CHECK (
  typ NOT IN ('dotace_priznana', 'dotace_cerpana', 'vratka') OR stav_dat_k IS NOT NULL
) NOT VALID;
COMMENT ON COLUMN core.castka.hodnota_czk IS
  'Přepočet cizoměnové částky kurzem ČNB k datu uzavření (kurz_datum = datum kurzu). Původní hodnota zůstává v hodnota/mena.';
COMMENT ON COLUMN core.castka.prepocet IS
  'neni_treba (CZK) | kurz_cnb (přepočteno) | kurz_nedostupny (kurz ČNB k datu nebyl k dispozici, nepřepočteno).';
COMMENT ON COLUMN core.castka.stav_dat_k IS 'Stav dat zdroje k datu (u dotací datum exportu/souboru zdroje, D-039).';

CREATE TABLE core.normalizace_beh (
  id                 bigserial PRIMARY KEY,
  zacatek            timestamptz NOT NULL DEFAULT clock_timestamp(),
  metodika_verze_id  uuid REFERENCES core.entita (id),
  parametry          jsonb,
  vlozeno            timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE core.normalizace_beh IS 'Běh normalizace raw -> core (parametry, souhrnné počty). Pouze INSERT.';

CREATE TABLE core.normalizace_vyjimka (
  id             bigserial PRIMARY KEY,
  beh_id         bigint NOT NULL REFERENCES core.normalizace_beh (id),
  raw_zaznam_id  bigint NOT NULL REFERENCES raw.zaznam (id),
  zdroj          text NOT NULL REFERENCES raw.zdroj (kod),
  druh           text NOT NULL CHECK (druh ~ '^[a-z0-9_]+$'),
  pole           text NOT NULL DEFAULT '',
  hodnota        text,
  popis          text,
  vlozeno        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (raw_zaznam_id, druh, pole)
);
CREATE INDEX normalizace_vyjimka_zdroj_druh_idx ON core.normalizace_vyjimka (zdroj, druh);
COMMENT ON TABLE core.normalizace_vyjimka IS
  'Výjimky normalizace (neplatné IČO, IČO nenalezené v kotvě, neznámá měna ...). Stejná výjimka téhož '
  'záznamu se zapíše jen jednou (první běh). Pouze INSERT.';

CREATE TRIGGER normalizace_beh_jen_insert BEFORE UPDATE OR DELETE ON core.normalizace_beh
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER normalizace_beh_bez_truncate BEFORE TRUNCATE ON core.normalizace_beh
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER normalizace_vyjimka_jen_insert BEFORE UPDATE OR DELETE ON core.normalizace_vyjimka
  FOR EACH ROW EXECUTE FUNCTION public.pvk_jen_insert();
CREATE TRIGGER normalizace_vyjimka_bez_truncate BEFORE TRUNCATE ON core.normalizace_vyjimka
  FOR EACH STATEMENT EXECUTE FUNCTION public.pvk_jen_insert();

-- Pokrytí: zadavatel/poskytovatel (plátce toku) × zdroj -> od kdy a do kdy ho zdroj zachycuje
-- (platnost toků ve světě), počet toků. Počítá se z aktuálních verzí (dnešní znalost).
CREATE VIEW core.pokryti_platcu AS
SELECT s.subjekt_id, s.ico, z.zdroj, t.druh AS druh_toku,
       min(t.valid_from) AS zachycen_od, max(t.valid_from) AS posledni_tok_od,
       count(DISTINCT t.tok_id) AS pocet_toku, min(z.recorded_from) AS v_platforme_od
  FROM core.tok_aktualni t
  JOIN core.subjekt_aktualni s ON s.subjekt_id = t.platce_subjekt_id AND s.valid_to = 'infinity'
  JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = t.tok_id
  JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id
 GROUP BY s.subjekt_id, s.ico, z.zdroj, t.druh;
COMMENT ON VIEW core.pokryti_platcu IS
  'Pokrytí zadavatelů/poskytovatelů: které zdroje je zachycují (druh toku) a od kdy (nejstarší platnost toku).';
