"""Validation a la frontiere raw -> staging, et aplatissement au format long.

C'est le seul endroit du pipeline ou l'on fait confiance a la source, et c'est donc
celui ou l'on verifie tout. Chaque rejet est **compte par champ et par motif**, avec un
exemple : une source qui derive doit se voir dans un rapport, pas faire tomber
l'execution sur une exception obscure trois etapes plus loin.

Les pieges traites ici viennent tous de `docs/reconnaissance.md` :

- les dates sont de l'heure locale de Paris malgre un suffixe `+00:00` (section 1.4) ;
- `latitude` et `longitude` sont du texte en degres x 100 000 : on utilise `geom`
  (section 1.3) ;
- les horaires sont en `HH.MM` avec un point, et le champ `horaire` d'une journee est
  tantot un objet, tantot une liste quand la journee a deux plages (section 1.7) ;
- `pop` ne vaut que `R` ou `A` (section 1.5) ;
- aucune station n'est en outre-mer dans ce flux (section 1.6).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from carburant_etl.carburants import CARBURANTS, CodeCarburant
from carburant_etl.config import EMPRISE_LATITUDE, EMPRISE_LONGITUDE
from carburant_etl.fuseau import HorodatageIllisible, lire_maj
from carburant_etl.transformation.aberrants import dans_les_bornes

RUPTURES_CONNUES: Final = frozenset({"temporaire", "definitive"})
JOURS: Final = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")


# ---------------------------------------------------------------- rejets


@dataclass(slots=True)
class Rejets:
    """Compteur de rejets, par champ et par motif, avec un exemple de chacun."""

    comptes: Counter[tuple[str, str]] = field(default_factory=Counter)
    exemples: dict[tuple[str, str], str] = field(default_factory=dict)

    def noter(self, champ: str, motif: str, exemple: object = None) -> None:
        """Enregistre un rejet. Seul le premier exemple de chaque couple est garde."""
        cle = (champ, motif)
        self.comptes[cle] += 1
        if cle not in self.exemples:
            self.exemples[cle] = repr(exemple)[:200]

    @property
    def total(self) -> int:
        return sum(self.comptes.values())

    def lignes(self) -> list[tuple[str, str, int, str | None]]:
        """Les rejets sous la forme chargee dans `staging.rejet`."""
        return [
            (champ, motif, nombre, self.exemples.get((champ, motif)))
            for (champ, motif), nombre in sorted(self.comptes.items())
        ]


# ---------------------------------------------------------------- lignes produites


@dataclass(frozen=True, slots=True)
class LigneStation:
    """Une station, telle qu'elle est chargee dans `staging.station`."""

    station_id: int
    longitude: float
    latitude: float
    cp: str | None
    adresse: str | None
    ville: str | None
    pop: str | None
    departement: str | None
    code_departement: str | None
    region: str | None
    code_region: str | None
    horaires: dict[str, Any] | None
    services: list[str]


@dataclass(frozen=True, slots=True)
class LignePrix:
    """Un couple station x carburant, tel qu'il est charge dans `staging.prix`."""

    station_id: int
    carburant: CodeCarburant
    prix: float | None
    maj: str | None
    """Horodatage ISO 8601 en UTC, pret pour un `COPY`."""
    rupture_type: str | None
    rupture_debut: str | None


@dataclass(frozen=True, slots=True)
class Aplatissement:
    """Resultat de la validation d'un export complet."""

    stations: list[LigneStation]
    prix: list[LignePrix]
    rejets: Rejets
    lignes_lues: int

    @property
    def stations_rejetees(self) -> int:
        return self.lignes_lues - len(self.stations)


# ---------------------------------------------------------------- helpers


def _texte(valeur: object) -> str | None:
    """Normalise une chaine : espaces retires, vide traite comme absent."""
    if not isinstance(valeur, str):
        return None
    propre = valeur.strip()
    return propre or None


def _heure(valeur: object) -> str | None:
    """Convertit une heure du flux (`08.00`) en `08:00`.

    Le flux utilise un point comme separateur, ce qu'aucun type SQL ne comprend.
    """
    texte = _texte(valeur)
    if texte is None:
        return None
    normalise = texte.replace(".", ":")
    heures, _, minutes = normalise.partition(":")
    if not (heures.isdigit() and minutes.isdigit()):
        return None
    h, m = int(heures), int(minutes)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def normaliser_horaires(brut: object) -> dict[str, Any] | None:
    """Normalise le champ `horaires` du flux en une structure stable.

    Le flux donne, par station :
    `{"@automate-24-24": "1", "jour": [{"@id": "1", "@nom": "Lundi", "@ferme": "",
      "horaire": {"@ouverture": "08.00", "@fermeture": "12.00"}}, ...]}`

    Trois pieges, tous constates en vrai :
    - `horaire` est **soit un objet, soit une liste** quand la journee a deux plages ;
    - `horaire` peut etre absent : la station est ouverte mais sans horaire declare ;
    - `@ferme = "1"` l'emporte sur toute plage presente -- on a vu des journees
      marquees fermees avec une plage `01.00 -> 01.00`.

    Renvoie `None` quand le champ est absent ou illisible, jamais une exception : un
    horaire mal forme ne doit pas faire perdre le prix de la station.
    """
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except json.JSONDecodeError:
            return None
    if not isinstance(brut, dict):
        return None

    jours_bruts = brut.get("jour")
    if isinstance(jours_bruts, dict):
        jours_bruts = [jours_bruts]
    if not isinstance(jours_bruts, list):
        jours_bruts = []

    jours: list[dict[str, Any]] = []
    for entree in jours_bruts:
        if not isinstance(entree, dict):
            continue
        identifiant = _texte(entree.get("@id"))
        if identifiant is None or not identifiant.isdigit():
            continue
        numero = int(identifiant)
        if not 1 <= numero <= 7:
            continue

        ferme = _texte(entree.get("@ferme")) == "1"
        plages: list[list[str]] = []
        if not ferme:
            horaire = entree.get("horaire")
            if isinstance(horaire, dict):
                horaire = [horaire]
            if isinstance(horaire, list):
                for plage in horaire:
                    if not isinstance(plage, dict):
                        continue
                    ouverture = _heure(plage.get("@ouverture"))
                    fermeture = _heure(plage.get("@fermeture"))
                    if ouverture is not None and fermeture is not None:
                        plages.append([ouverture, fermeture])

        jours.append(
            {
                "jour": numero,
                "nom": JOURS[numero - 1],
                "ferme": ferme,
                "plages": plages,
            }
        )

    return {
        "automate_24_24": _texte(brut.get("@automate-24-24")) == "1",
        "jours": sorted(jours, key=lambda j: int(j["jour"])),
    }


def _services(brut: object) -> list[str]:
    """Normalise la liste des services. Le json du flux donne de vraies listes."""
    if isinstance(brut, list):
        return [s.strip() for s in brut if isinstance(s, str) and s.strip()]
    if isinstance(brut, str) and brut.strip():
        # Repli pour le csv, ou les multivalues sont concatenees.
        return [s.strip() for s in brut.split(",") if s.strip()]
    return []


def _maj(brut: object, champ: str, rejets: Rejets) -> str | None:
    """Lit une date du flux en heure de Paris et la rend en ISO 8601 UTC."""
    texte = _texte(brut)
    if texte is None:
        return None
    try:
        return lire_maj(texte).isoformat()
    except HorodatageIllisible:
        rejets.noter(champ, "horodatage illisible", brut)
        return None


# ---------------------------------------------------------------- aplatissement


class Geom(BaseModel):
    """Le point de la station, tel que le flux le donne dans `geom`.

    On n'utilise jamais `latitude` / `longitude` : ce sont des chaines en degres
    x 100 000, heritees du format amont et non converties par data.economie. Leur
    coherence avec `geom` a ete verifiee sur les 9 826 stations, sans un seul ecart
    (docs/reconnaissance.md section 1.3).
    """

    model_config = ConfigDict(extra="ignore")

    lat: Annotated[float, Field(ge=EMPRISE_LATITUDE[0], le=EMPRISE_LATITUDE[1])]
    lon: Annotated[float, Field(ge=EMPRISE_LONGITUDE[0], le=EMPRISE_LONGITUDE[1])]


class StationFlux(BaseModel):
    """Une ligne de l'export, validee.

    Seule l'enveloppe de la station est decrite ici. Les 24 colonnes de prix
    (6 carburants x prix, maj, type et debut de rupture) sont traitees par une boucle
    pilotee par la table `CARBURANTS` : ajouter un carburant doit couter une ligne
    dans cette table, pas quatre champs de plus dans ce modele. Elles sont validees et
    comptees de la meme facon, dans `_prix_de`.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: int
    geom: Geom
    cp: str | None = None
    adresse: str | None = None
    ville: str | None = None
    pop: Annotated[str, Field(pattern="^[RA]$")] | None = None
    departement: str | None = None
    code_departement: str | None = None
    region: str | None = None
    code_region: str | None = None
    horaires: dict[str, Any] | None = None
    services_service: list[str] = Field(default_factory=list)

    @field_validator(
        "cp",
        "adresse",
        "ville",
        "departement",
        "code_departement",
        "region",
        "code_region",
        mode="after",
    )
    @classmethod
    def _vide_vaut_absent(cls, valeur: str | None) -> str | None:
        """Une chaine vide est une absence, pas une valeur."""
        return valeur or None

    @field_validator("horaires", mode="before")
    @classmethod
    def _horaires_normalises(cls, valeur: object) -> dict[str, Any] | None:
        """Normalise les horaires avant validation.

        Un horaire mal forme vaut `None` plutot qu'une erreur : il ne doit pas faire
        perdre le prix de la station.
        """
        return normaliser_horaires(valeur)

    @field_validator("services_service", mode="before")
    @classmethod
    def _services_normalises(cls, valeur: object) -> list[str]:
        return _services(valeur)

    def en_ligne(self) -> LigneStation:
        """Convertit en ligne prete pour `COPY`."""
        return LigneStation(
            station_id=self.id,
            longitude=self.geom.lon,
            latitude=self.geom.lat,
            cp=self.cp,
            adresse=self.adresse,
            ville=self.ville,
            pop=self.pop,
            departement=self.departement,
            code_departement=self.code_departement,
            region=self.region,
            code_region=self.code_region,
            horaires=self.horaires,
            services=self.services_service,
        )


def _noter_erreurs_pydantic(erreur: ValidationError, rejets: Rejets) -> None:
    """Reporte les erreurs d'un `ValidationError` dans le compteur de rejets.

    Un champ par ligne d'erreur, avec le message de pydantic comme motif : c'est ce
    qui rend un rapport de qualite lisible sans ouvrir le code.
    """
    for detail in erreur.errors():
        champ = ".".join(str(part) for part in detail["loc"]) or "ligne"
        rejets.noter(champ, detail["msg"], detail.get("input"))


def _prix_de(brut: Mapping[str, Any], station_id: int, rejets: Rejets) -> list[LignePrix]:
    """Produit une ligne par carburant ayant un prix ou une rupture declaree."""
    lignes: list[LignePrix] = []
    for carburant in CARBURANTS:
        prefixe = carburant.champ_flux

        prix = brut.get(f"{prefixe}_prix")
        if prix is not None and not isinstance(prix, (int, float)):
            rejets.noter(f"{prefixe}_prix", "prix non numerique", prix)
            prix = None
        if prix is not None and not dans_les_bornes(carburant.code, float(prix)):
            # Hors bornes absolues : ce n'est pas un prix. Rejete et compte.
            rejets.noter(f"{prefixe}_prix", "hors bornes absolues", prix)
            prix = None

        maj = _maj(brut.get(f"{prefixe}_maj"), f"{prefixe}_maj", rejets)
        if prix is not None and maj is None:
            # Un prix sans date est inaffichable : la spec interdit le prix nu.
            rejets.noter(f"{prefixe}_prix", "prix sans date de mise a jour", prix)
            prix = None

        rupture_type = _texte(brut.get(f"{prefixe}_rupture_type"))
        if rupture_type is not None and rupture_type not in RUPTURES_CONNUES:
            rejets.noter(f"{prefixe}_rupture_type", "type inattendu", rupture_type)
            rupture_type = None
        rupture_debut = _maj(
            brut.get(f"{prefixe}_rupture_debut"), f"{prefixe}_rupture_debut", rejets
        )

        if prix is None and rupture_type is None:
            continue

        lignes.append(
            LignePrix(
                station_id=station_id,
                carburant=carburant.code,
                prix=round(float(prix), 3) if prix is not None else None,
                maj=maj if prix is not None else None,
                rupture_type=rupture_type,
                rupture_debut=rupture_debut if rupture_type is not None else None,
            )
        )
    return lignes


def aplatir(export: Sequence[object]) -> Aplatissement:
    """Valide un export complet et le met au format long.

    L'entree est typee `Sequence[object]` et non `list[dict]` a dessein : elle sort
    d'un `json.load` sur une source externe. Pretendre connaitre sa forme avant de
    l'avoir verifiee reviendrait a faire confiance a ce qu'on est justement en train
    de valider.

    Ne leve jamais sur une ligne mal formee : elle est comptee et ecartee. Une seule
    station cassee ne doit pas priver l'utilisateur des 9 825 autres.
    """
    rejets = Rejets()
    stations: list[LigneStation] = []
    prix: list[LignePrix] = []

    vues: set[int] = set()
    for brut in export:
        if not isinstance(brut, dict):
            rejets.noter("ligne", "entree non objet", brut)
            continue
        try:
            validee = StationFlux.model_validate(brut)
        except ValidationError as erreur:
            _noter_erreurs_pydantic(erreur, rejets)
            continue

        if validee.id in vues:
            # Deux lignes pour la meme station dans un meme export : la source n'est
            # pas censee le faire, mais on ne laisse pas passer en silence.
            rejets.noter("id", "station en double dans l'export", validee.id)
            continue
        vues.add(validee.id)
        stations.append(validee.en_ligne())
        prix.extend(_prix_de(brut, validee.id, rejets))

    return Aplatissement(stations=stations, prix=prix, rejets=rejets, lignes_lues=len(export))
