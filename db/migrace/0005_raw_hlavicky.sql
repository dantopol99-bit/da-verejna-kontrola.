-- 0005: vybrané hlavičky HTTP odpovědi v logu stažení (Last-Modified, ETag, X-Total-Count...).
-- Pomáhají doložit stav zdroje v okamžiku stažení a jsou potřeba pro výběry ze stránkovaných API.

ALTER TABLE raw.stazeni ADD COLUMN hlavicky jsonb;
COMMENT ON COLUMN raw.stazeni.hlavicky IS
  'Vybrané hlavičky odpovědi (content-length, last-modified, etag, x-total-count, content-range).';
