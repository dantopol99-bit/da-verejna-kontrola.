# Platforma veřejné kontroly

Druhý systém platformy Datové pole: toky veřejných peněz (smlouvy, zakázky, dotace) napojené
na kotvu – Firemní databázi – přes IČO.

* Pravidla a konvence: [CLAUDE.md](CLAUDE.md)
* Rozhodnutí: [docs/decisions.md](docs/decisions.md)
* Zdroje dat a jejich endpointy: [docs/sources.md](docs/sources.md)
* Pilot měření kvality dat: [docs/pilot_report.md](docs/pilot_report.md),
  výjimky k potvrzení [docs/pilot_vyjimky.csv](docs/pilot_vyjimky.csv),
  metodika [metodika/pilot-2026.09.md](metodika/pilot-2026.09.md)

## Rychlý start

```
cp .env.example .env     # volitelné
make test                # vytvoří .venv, spustí PostgreSQL, migrace a testy
make pilot               # celý pilot jedním příkazem
```

Požadavky: Python 3.12, Docker (nebo lokální PostgreSQL 16), pro OCR skenovaných smluv
`tesseract-ocr`, `tesseract-ocr-ces` a `poppler-utils`.
