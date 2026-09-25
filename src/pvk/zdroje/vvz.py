"""Věstník veřejných zakázek (VVZ) – veřejné JSON API webu vvz.nipez.cz.

Web VVZ je aplikace nad API https://api.vvz.nipez.cz (bez přihlášení):
  GET /api/submissions/search           vyhledávání formulářů (filtry data.*, stránkování page/limit,
                                        počet v hlavičce X-Total-Count)
  GET /api/submissions/children/search  úplný obsah formuláře eForms (strom ND-Root s poli BT-*)
  GET /api/submissions/public/{publicId}

Oficiální otevřená data o zakázkách publikuje ISVZ (isvz.nipez.cz/opendata); z této session nebyla
dosažitelná (viz docs/sources.md), proto pilot čte přímo VVZ.

Z formulářů eForms bereme:
  BT-501 IČO organizace, BT-500 název          BT-27 předpokládaná hodnota (bez DPH)
  BT-720 hodnota vítězné nabídky (bez DPH)     BT-145 datum uzavření smlouvy
  BT-150 identifikátor smlouvy                 BT-151 URL smlouvy (často odkaz do registru smluv)
  BT-142 výsledek části (selec-w = vybrán dodavatel)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pvk.http import Odpoved, Stahovac
from pvk.ico import normalizuj_ico

ZDROJ = "vvz"
API = "https://api.vvz.nipez.cz"
WEB = "https://vvz.nipez.cz"
RE_ODKAZ_RS = re.compile(r"smlouvy\.gov\.cz/smlouva/(\d+)")


def seznam(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _datum(hodnota) -> date | None:
    if not hodnota:
        return None
    try:
        return date.fromisoformat(str(hodnota)[:10])
    except ValueError:
        return None


def _castka(hodnota) -> tuple[Decimal | None, str | None]:
    if isinstance(hodnota, dict):
        v = hodnota.get("_value")
        return (Decimal(str(v)) if v is not None else None), hodnota.get("_currencyID")
    if hodnota is None:
        return None, None
    return Decimal(str(hodnota)), None


@dataclass
class OrganizaceVVZ:
    id: str
    ico: str | None
    nazev: str | None


@dataclass
class SmlouvaVVZ:
    """Uzavřená smlouva z oznámení o výsledku (ND-SettledContract)."""

    id: str
    identifikator: str | None
    datum_uzavreni: date | None
    url: list[str]
    hodnota: Decimal | None
    mena: str | None
    dodavatele: list[OrganizaceVVZ]
    casti: list[str] = field(default_factory=list)

    @property
    def id_verzi_rs(self) -> list[str]:
        return sorted({m.group(1) for u in self.url for m in [RE_ODKAZ_RS.search(u)] if m})


@dataclass
class OznameniVVZ:
    id: str
    public_id: str
    ev_cislo_formulare: str
    ev_cislo_zakazky: str | None
    druh_formulare: str
    nazev: str | None
    datum_uverejneni: date | None
    zadavatele: list[OrganizaceVVZ]
    smlouvy: list[SmlouvaVVZ]
    predpokladana_hodnota: Decimal | None
    predpokladana_mena: str | None
    hodnota_vysledku: Decimal | None
    hodnota_vysledku_mena: str | None
    zdroj_podani: str | None
    vybran_dodavatel: bool

    @property
    def odkaz(self) -> str:
        return f"{WEB}/vyhledat-formular/{self.public_id}"


def _organizace(root: dict) -> dict[str, OrganizaceVVZ]:
    orgs = {}
    for o in seznam(root.get("ND-RootExtension", {}).get("ND-Organizations", {}).get("ND-Organization")):
        firma = o.get("ND-Company", {})
        oid = firma.get("OPT-200-Organization-Company")
        ico = None
        for le in seznam(firma.get("ND-CompanyLegalEntity")):
            ico = ico or normalizuj_ico(le.get("BT-501-Organization-Company"))
        if oid:
            orgs[oid] = OrganizaceVVZ(oid, ico, firma.get("BT-500-Organization-Company"))
    return orgs


def parsuj_eforms(souhrn: dict, deti: list[dict]) -> OznameniVVZ | None:
    """souhrn = položka z /api/submissions/search, deti = /api/submissions/children/search."""
    data = souhrn.get("data", {})
    root = None
    for d in deti:
        if isinstance(d.get("data"), dict) and "ND-Root" in d["data"]:
            root = d["data"]["ND-Root"]
            break
    if root is None:
        return None
    orgs = _organizace(root)
    vysledek = root.get("ND-RootExtension", {}).get("ND-NoticeResult", {})

    zadavatele = []
    for cp in seznam(root.get("ND-ContractingParty")):
        oid = cp.get("ND-Buyer", {}).get("OPT-300-Procedure-Buyer")
        if oid in orgs:
            zadavatele.append(orgs[oid])
    if not zadavatele:  # záloha: IČO zadavatelů ze souhrnu formuláře
        zadavatele = [OrganizaceVVZ("", normalizuj_ico(z.get("ico")), z.get("nazev")) for z in seznam(data.get("zadavatele"))]

    strany = {}  # TPA -> [organizace]
    for tp in seznam(vysledek.get("ND-TenderingParty")):
        strany[tp.get("OPT-210-Tenderer")] = [
            orgs[t.get("OPT-300-Tenderer")] for t in seznam(tp.get("ND-Tenderer")) if t.get("OPT-300-Tenderer") in orgs
        ]
    nabidky = {}  # technické ID nabídky (OPT-321, "TEN-0001") -> (hodnota, měna, [organizace], část)
    for t in seznam(vysledek.get("ND-LotTender")):
        h, m = _castka(t.get("BT-720-Tender"))
        udaje = (h, m, strany.get(t.get("OPT-310-Tender"), []), t.get("BT-13714-Tender"))
        # smlouva odkazuje na nabídku technickým ID (BT-3202 = OPT-321); BT-3201 je označení zadavatele
        for klic in (t.get("OPT-321-Tender"), t.get("BT-3201-Tender")):
            if klic and klic not in nabidky:
                nabidky[klic] = udaje

    vybran = any(lr.get("BT-142-LotResult") == "selec-w" for lr in seznam(vysledek.get("ND-LotResult")))
    smlouvy = []
    for sc in seznam(vysledek.get("ND-SettledContract")):
        hodnota, mena, dodavatele, casti = None, None, [], []
        for ref in seznam(sc.get("ND-SettledContractTenderReference")):
            n = nabidky.get(ref.get("BT-3202-Contract"))
            if n:
                if n[0] is not None:
                    hodnota = (hodnota or Decimal(0)) + n[0]
                    mena = mena or n[1]
                dodavatele += [o for o in n[2] if o not in dodavatele]
                if n[3]:
                    casti.append(n[3])
        smlouvy.append(
            SmlouvaVVZ(
                id=sc.get("OPT-316-Contract") or sc.get("BT-150-Contract") or "",
                identifikator=sc.get("BT-150-Contract"),
                datum_uzavreni=_datum(sc.get("BT-145-Contract")),
                url=[u for u in seznam(sc.get("BT-151-Contract")) if isinstance(u, str)],
                hodnota=hodnota,
                mena=mena,
                dodavatele=dodavatele,
                casti=casti,
            )
        )

    odhad, odhad_mena = _castka(
        root.get("ND-ProcedureProcurementScope", {}).get("ND-ProcedureValueEstimate", {}).get("BT-27-Procedure")
    )
    celkem, celkem_mena = _castka(vysledek.get("BT-161-NoticeResult"))
    return OznameniVVZ(
        id=souhrn["id"],
        public_id=souhrn.get("publicId", ""),
        ev_cislo_formulare=souhrn.get("variableId", ""),
        ev_cislo_zakazky=data.get("evCisloZakazkyVvz"),
        druh_formulare=str(data.get("druhFormulare")),
        nazev=data.get("nazevZakazky"),
        datum_uverejneni=_datum(data.get("datumUverejneniVvz")),
        zadavatele=zadavatele,
        smlouvy=smlouvy,
        predpokladana_hodnota=odhad,
        predpokladana_mena=odhad_mena,
        hodnota_vysledku=celkem,
        hodnota_vysledku_mena=celkem_mena,
        zdroj_podani=(data.get("zdrojPodani") or {}).get("typ"),
        vybran_dodavatel=vybran,
    )


class VVZ:
    def __init__(self, stahovac: Stahovac):
        self.s = stahovac

    @staticmethod
    def filtry_vysledku(od: date, do: date, formulare: list[str]) -> dict:
        return {
            "formGroup": "vz",
            "form": "vz",
            "workflowPlace": "UVEREJNENO_VVZ",
            "data.datumUverejneniVvz[gte]": od.isoformat(),
            "data.datumUverejneniVvz[lt]": do.isoformat(),
            "data.druhFormulare[]": list(formulare),
            "order[variableId]": "asc",
        }

    def hledej(self, filtry: dict, strana: int, limit: int = 1) -> tuple[Odpoved, list[dict]]:
        odp = self.s.ziskej(ZDROJ, f"{API}/api/submissions/search", params={**filtry, "page": strana, "limit": limit})
        if odp.status != 200:
            return odp, []
        return odp, json.loads(odp.obsah())

    def pocet(self, filtry: dict) -> int:
        odp, _ = self.hledej(filtry, 1, 1)
        if odp.status != 200 or not odp.hlavicky or "x-total-count" not in odp.hlavicky:
            raise RuntimeError(f"VVZ: nelze zjistit počet formulářů ({odp.status} {odp.chyba})")
        return int(odp.hlavicky["x-total-count"])

    def deti(self, submission_id: str) -> tuple[Odpoved, list[dict]]:
        odp = self.s.ziskej(ZDROJ, f"{API}/api/submissions/children/search", params={"submission": submission_id, "limit": 5})
        if odp.status != 200:
            return odp, []
        return odp, json.loads(odp.obsah())
