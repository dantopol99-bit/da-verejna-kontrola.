-- 0010: core.castka.prepocet bez NOT NULL.
-- core.zapis_verzi() plní sloupce z jsonb (chybějící klíč = NULL, výchozí hodnota se neuplatní), takže
-- NOT NULL z migrace 0009 odmítal zápisy částek bez údaje o přepočtu (i u CZK). NULL u CZK znamená
-- „přepočet není třeba“; cizí měna musí přepočet uvést vždy (kurz_cnb, nebo kurz_nedostupny).

ALTER TABLE core.castka ALTER COLUMN prepocet DROP NOT NULL;
ALTER TABLE core.castka ADD CONSTRAINT castka_cizi_mena_uvadi_prepocet
  CHECK (mena = 'CZK' OR prepocet IS NOT NULL) NOT VALID;
