"""Konfigurace z prostředí (a volitelně ze souboru .env v kořeni repozitáře)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]


def _nacti_env_soubor(cesta: Path) -> None:
    """Minimální čtení .env: KLIC=hodnota, komentáře '#'. Proměnné prostředí mají přednost."""
    if not cesta.is_file():
        return
    for radek in cesta.read_text(encoding="utf-8").splitlines():
        radek = radek.strip()
        if not radek or radek.startswith("#") or "=" not in radek:
            continue
        klic, hodnota = radek.split("=", 1)
        os.environ.setdefault(klic.strip(), hodnota.strip())


_nacti_env_soubor(KOREN / ".env")


@dataclass(frozen=True)
class Nastaveni:
    database_url: str
    data_dir: Path
    user_agent: str
    pilot_seed: int
    pilot_obdobi_od: date
    pilot_obdobi_do: date
    rs_backend: str  # provoz: jen "oficialni" (D-030)
    pilot_rs_backend: str  # pilot: "auto" = oficiální, při nedostupnosti zrcadlo
    kotva: str
    kotva_database_url: str | None


def nastaveni() -> Nastaveni:
    data_dir = Path(os.environ.get("PVK_DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = KOREN / data_dir
    return Nastaveni(
        database_url=os.environ.get("DATABASE_URL", "postgresql://pvk:pvk@localhost:55432/pvk"),
        data_dir=data_dir,
        user_agent=os.environ.get(
            "PVK_USER_AGENT", "DatovePole-PVK/0.1 (pilot mereni kvality dat; nizka frekvence dotazu)"
        ),
        pilot_seed=int(os.environ.get("PVK_PILOT_SEED", "20260925")),
        pilot_obdobi_od=date.fromisoformat(os.environ.get("PVK_PILOT_OBDOBI_OD", "2025-09-01")),
        pilot_obdobi_do=date.fromisoformat(os.environ.get("PVK_PILOT_OBDOBI_DO", "2026-09-01")),
        rs_backend=os.environ.get("PVK_RS_BACKEND", "oficialni"),
        pilot_rs_backend=os.environ.get("PVK_PILOT_RS_BACKEND", "auto"),
        kotva=os.environ.get("PVK_KOTVA", "ares"),
        kotva_database_url=os.environ.get("KOTVA_DATABASE_URL"),
    )
