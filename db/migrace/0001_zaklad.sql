-- 0001: schémata a rozšíření.
-- Migrace jsou neměnné: jednou aplikovaný soubor se už nemění (runner hlídá SHA-256),
-- změna struktury = nový soubor s vyšším číslem.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ind;

COMMENT ON SCHEMA raw IS
  'Neměnná zdrojová vrstva. Pouze INSERT. Každý záznam nese zdroj, ID ve zdroji, soubor/URL, čas stažení a hash.';
COMMENT ON SCHEMA core IS
  'Bitemporální model: valid_from/valid_to (platnost ve světě) + recorded_from/recorded_to (kdy to víme). '
  'Nic se nepřepisuje, změna = nová verze (core.zapis_verzi).';
COMMENT ON SCHEMA ind IS
  'Výsledky indikátorů a souhrny. Pouze INSERT. Indikátor je signál k prověření, nikdy zjištění.';

-- Společná pojistka neměnnosti pro tabulky "pouze INSERT" (raw.*, core.entita, ind.*).
CREATE FUNCTION public.pvk_jen_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Tabulka %.% je pouze pro INSERT: operace % není povolena', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'PV001';
END $$;

COMMENT ON FUNCTION public.pvk_jen_insert() IS
  'Trigger: zakazuje UPDATE, DELETE a TRUNCATE (SQLSTATE PV001).';
