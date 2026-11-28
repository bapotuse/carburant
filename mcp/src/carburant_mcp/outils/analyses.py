"""Les trois outils qui répondent à « comment ça évolue ? » et « combien ça pèse ? ».

Deux d'entre eux donnent des chiffres qu'on ne peut pas vérifier d'un coup d'œil : une
tendance sur un an et une empreinte carbone. Ils portent donc leur provenance, et les
descriptions insistent là-dessus — un facteur d'émission sans sa source ne vaut rien,
et un modèle de langage qui le cite sans la source produit un chiffre orphelin qui se
propagera.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from carburant_mcp.carburants import CODES, libelle, normaliser
from carburant_mcp.client import ClientCarburant, ErreurAPI
from carburant_mcp.erreurs import relayer
from carburant_mcp.formats import co2_kg, nombre, pluriel, prix_litre
from carburant_mcp.formats import litres as litres_affiches
from carburant_mcp.lieux import geocoder

LECTURE_SEULE = ToolAnnotations(read_only_hint=True, open_world_hint=True)

PERIODES: Final[dict[str, int]] = {
    "semaine": 7,
    "mois": 30,
    "trimestre": 90,
    "semestre": 182,
    "an": 365,
    "annee": 365,
    "année": 365,
    "2 ans": 730,
    "5 ans": 1825,
}
"""Les durées qu'on accepte en mots. Un modèle écrit « ce mois-ci », pas « 30 »."""

JOURS_MAX: Final = 1825
"""Cinq ans. Au-delà, la série dépasse ce qu'un modèle peut restituer utilement, et
l'historique complet se lit mieux sur le site."""


class ReponseTendance(BaseModel):
    """L'évolution d'un prix sur une période."""

    carburant: str
    carburant_libelle: str
    zone: str = Field(description="Ce sur quoi porte la serie : « France » ou un departement.")
    jours: int
    prix_debut_eur_l: float | None = None
    prix_fin_eur_l: float | None = None
    variation_eur_l: float | None = Field(
        default=None, description="Negatif quand le prix a baisse."
    )
    variation_pourcent: float | None = None
    prix_min_eur_l: float | None = None
    prix_max_eur_l: float | None = None
    points: int = Field(default=0, description="Jours couverts par la serie.")
    texte: str


class ReponseEmpreinte(BaseModel):
    """L'empreinte carbone d'un plein, avec sa source."""

    carburant: str
    carburant_libelle: str
    litres: float
    co2_kg: float
    facteur_kg_co2e_par_litre: float
    source: dict[str, Any] = Field(
        description=(
            "Provenance complete du facteur : libelle exact de l'ADEME, perimetre, "
            "periode de validite, version du jeu et URL. **A citer avec le chiffre.**"
        )
    )
    texte: str


class ReponseComparaison(BaseModel):
    """Les six carburants comparés, en prix et en CO2."""

    lieu: str | None = None
    litres: float
    carburants: list[dict[str, Any]] = Field(
        description="Un element par carburant : prix local quand il existe, CO2 du plein."
    )
    avertissement: str = Field(
        description="Ce que la comparaison ne dit pas. A relayer, pas a resumer."
    )
    source_co2: str
    texte: str


def _jours(periode: str) -> int:
    """Traduit « ce mois-ci », « sur un an », « 90 jours » en un nombre de jours."""
    texte = periode.strip().lower()
    if not texte:
        return 30
    for mot, jours in PERIODES.items():
        if mot in texte:
            return jours
    chiffres = re.search(r"(\d+)", texte)
    if chiffres:
        valeur = int(chiffres.group(1))
        # « 12 mois » et « 12 jours » ne sont pas la même chose : on lit l'unité.
        if "mois" in texte:
            valeur *= 30
        elif "an" in texte:
            valeur *= 365
        elif "semaine" in texte:
            valeur *= 7
        return max(1, min(valeur, JOURS_MAX))
    raise ErreurAPI(
        f"Periode « {periode} » incomprise. Ecris par exemple « ce mois-ci », "
        "« sur un an », « 90 jours », ou « 2 ans »."
    )


def _departement(zone: str) -> str | None:
    """Un code de département si `zone` en est un, sinon None.

    On accepte les codes a deux chiffres et la Corse (2A, 2B). Un nom de departement
    demanderait une table des cent-un noms, qui n'existe pas encore dans le projet :
    on geocode alors la zone et on en tire le code postal.
    """
    texte = zone.strip().upper()
    if re.fullmatch(r"(0[1-9]|[1-8]\d|9[0-5]|2A|2B)", texte):
        return texte
    return None


def enregistrer(serveur: MCPServer[Any], client: ClientCarburant) -> None:
    """Déclare les trois outils d'analyse sur le serveur."""

    @serveur.tool(
        name="tendance_prix",
        title="Évolution du prix d'un carburant",
        description=(
            "L'evolution du prix d'un carburant sur une periode, en France ou dans un "
            "departement.\n\n"
            "**Choisis cet outil** pour « le gazole a-t-il baisse ce mois-ci ? », "
            "« les prix montent-ils dans les Bouches-du-Rhone ? », « combien coutait le "
            "diesel il y a un an ? ». Pour un prix maintenant, prends "
            "`trouver_station_moins_chere`.\n\n"
            "`zone` accepte « France », un code de departement (« 13 », « 2A ») ou un "
            "lieu en texte libre, dont on tire le departement. `periode` accepte des "
            "mots : « ce mois-ci », « sur un an », « 90 jours », « 2 ans ». Au-dela de "
            "cinq ans, renvoie l'utilisateur vers le site.\n\n"
            "**Ces moyennes portent sur les prix en vigueur chaque jour**, pas sur les "
            "seuls prix modifies ce jour-la : le flux officiel ne publie que les "
            "changements, et moyenner les changements ne compterait que les stations "
            "qui bougent souvent. Les prix atypiques et perimes sont ecartes du calcul.\n\n"
            "La serie commence en 2007. Si `points` est bien plus petit que `jours`, "
            "c'est que la periode demandee depasse l'historique charge : dis-le."
        ),
        annotations=LECTURE_SEULE,
    )
    async def tendance_prix(
        zone: Annotated[
            # `str | int` : un code de departement s'ecrit « 13 » et un client le
            # passe volontiers en nombre. Voir la note de `prix_station`.
            str | int,
            Field(description="« France », un code de departement, ou un lieu."),
        ] = "France",
        carburant: Annotated[str, Field(description="Carburant, synonymes acceptes.")] = "gazole",
        periode: Annotated[
            str, Field(description="« ce mois-ci », « sur un an », « 90 jours ».")
        ] = "mois",
    ) -> ReponseTendance:
        with relayer():
            code = normaliser(carburant)
            jours = _jours(periode)
            texte_zone = str(zone).strip()
            departement: str | None = None
            nom_zone = "France"
            if texte_zone and texte_zone.lower() not in ("france", "nationale", "national"):
                departement = _departement(texte_zone)
                if departement is None:
                    place = await geocoder(client, texte_zone)
                    # Le code postal donne le departement, sauf en Corse ou 20xxx
                    # couvre 2A et 2B : on ne devine pas, on reste national et on le dit.
                    if place.code_postal and not place.code_postal.startswith("20"):
                        departement = place.code_postal[:2]
                        nom_zone = place.ville or place.libelle
                    else:
                        nom_zone = "France"
                else:
                    nom_zone = f"departement {departement}"
            brut = await client.obtenir(
                "/tendances", carburant=code, departement=departement, jours=jours
            )

        points = brut.get("points") or []
        if not points:
            return ReponseTendance(
                carburant=code,
                carburant_libelle=libelle(code),
                zone=nom_zone,
                jours=jours,
                texte=(
                    f"Aucune donnee de {libelle(code)} pour {nom_zone} sur cette periode. "
                    "L'historique commence en 2007, mais un departement peut manquer de "
                    "stations certains jours."
                ),
            )

        debut = float(points[0]["prix_median_eur_l"])
        fin = float(points[-1]["prix_median_eur_l"])
        variation = round(fin - debut, 3)
        pourcent = round(100 * variation / debut, 2) if debut else None
        bas = min(float(p["prix_min_eur_l"]) for p in points)
        haut = max(float(p["prix_max_eur_l"]) for p in points)

        sens = "baisse" if variation < 0 else ("hausse" if variation > 0 else "stabilite")
        centimes = abs(variation) * 100
        if variation == 0:
            mouvement = "stable"
        else:
            mouvement = f"en {sens} de {nombre(centimes, 1)} centimes par litre"
        texte = (
            f"{libelle(code).capitalize()} en {nom_zone}, sur {pluriel(len(points), 'jour')} : "
            f"{mouvement}, de {prix_litre(debut)} a {prix_litre(fin)}"
            + (f" ({nombre(pourcent, 1)} %)" if pourcent is not None else "")
            + f". Extremes de la periode : {prix_litre(bas)} a {prix_litre(haut)}."
        )
        if len(points) < jours * 0.5:
            texte += (
                # Tournure sans verbe apres le nombre : « 1 jour sont couverts » et
                # « 2 jour est couvert » sont tous deux faux, et accorder un verbe en
                # plus du nom pour une phrase d'avertissement ne vaut pas la peine.
                " Attention, la periode demandee depasse l'historique disponible pour "
                f"cette zone : {pluriel(len(points), 'jour')} couvert"
                f"{'s' if len(points) > 1 else ''} sur {jours}."
            )

        return ReponseTendance(
            carburant=code,
            carburant_libelle=libelle(code),
            zone=nom_zone,
            jours=jours,
            prix_debut_eur_l=debut,
            prix_fin_eur_l=fin,
            variation_eur_l=variation,
            variation_pourcent=pourcent,
            prix_min_eur_l=bas,
            prix_max_eur_l=haut,
            points=len(points),
            texte=texte,
        )

    @serveur.tool(
        name="empreinte_carbone_plein",
        title="Empreinte carbone d'un plein",
        description=(
            "Le CO2 equivalent d'un plein, a partir des facteurs d'emission de la Base "
            "Carbone de l'ADEME.\n\n"
            "**Choisis cet outil** pour « combien de CO2 pour un plein de 50 L de "
            "gazole ? », « quel carburant pollue le moins ? » (avec "
            "`comparer_carburants` pour les six).\n\n"
            "**Cite la source avec le chiffre.** La reponse porte le libelle exact de "
            "l'ADEME, le perimetre geographique, la periode de validite, la version du "
            "jeu de donnees et son URL. Un facteur d'emission sans sa source ne vaut "
            "rien, et il se propagera.\n\n"
            "Ce facteur couvre la **combustion et l'amont du carburant**, pas la "
            "fabrication du vehicule ni son entretien. L'E85 affiche un facteur bas "
            "parce que le carbone de la biomasse n'y est pas compte : c'est la "
            "convention de la Base Carbone, pas une neutralite reelle. Dis-le si on te "
            "demande de comparer les carburants sur l'environnement.\n\n"
            "Si aucun facteur n'est charge, l'outil refuse. **N'estime pas a la place.**"
        ),
        annotations=LECTURE_SEULE,
    )
    async def empreinte_carbone_plein(
        carburant: Annotated[str, Field(description="Carburant, synonymes acceptes.")],
        litres: Annotated[float, Field(gt=0, le=500, description="Volume du plein.")] = 40.0,
    ) -> ReponseEmpreinte:
        with relayer():
            code = normaliser(carburant)
            brut = await client.obtenir("/empreinte", carburant=code, litres=litres)

        facteur = brut["facteur"]
        masse = float(brut["co2_kg"])
        texte = (
            f"Un plein de {litres_affiches(litres)} de {libelle(code)} represente "
            f"{co2_kg(masse)}, soit {nombre(float(facteur['valeur_kg_co2e_par_litre']), 3)} "
            f"kg CO2e par litre. Source : ADEME, Base Carbone, "
            f"« {facteur['libelle_ademe']} »"
            + (f", {facteur['localisation']}" if facteur.get("localisation") else "")
            + (
                f", validite {facteur['periode_validite']}"
                if facteur.get("periode_validite")
                else ""
            )
            + f" (jeu du {facteur['version_base']})."
        )
        return ReponseEmpreinte(
            carburant=code,
            carburant_libelle=libelle(code),
            litres=litres,
            co2_kg=masse,
            facteur_kg_co2e_par_litre=float(facteur["valeur_kg_co2e_par_litre"]),
            source=facteur,
            texte=texte,
        )

    @serveur.tool(
        name="comparer_carburants",
        title="Comparer les six carburants",
        description=(
            "Les six carburants cote a cote : prix local quand un lieu est donne, et "
            "CO2 d'un plein.\n\n"
            "**Choisis cet outil** pour « quel carburant est le plus economique ? », "
            "« essence ou diesel ? », « et le GPL, ca vaut le coup ? ».\n\n"
            "Sans `lieu`, la comparaison ne porte que sur le CO2. Avec un lieu, elle "
            "ajoute le prix de chaque carburant dans un rayon de 10 km — et un "
            "carburant peut manquer. Mesure sur les 9 825 stations actives : le gazole "
            "a un prix dans 97 % d'entre elles, le SP98 et l'E10 dans 78 %, l'E85 dans "
            "40 %, le SP95 dans 29 % et le GPL dans 15 %. Un carburant absent de la "
            "reponse n'est pas gratuit, il est introuvable sur place.\n\n"
            "**Ce que cette comparaison ne dit pas**, et qu'il faut relayer : un litre "
            "d'E85 ne fait pas la meme distance qu'un litre de gazole, donc comparer "
            "les prix au litre ne compare pas les couts d'usage. Le champ "
            "`avertissement` le dit ; ne le resume pas en « l'E85 est le moins cher »."
        ),
        annotations=LECTURE_SEULE,
    )
    async def comparer_carburants(
        lieu: Annotated[
            str | None,
            Field(default=None, description="Lieu pour les prix locaux. Omis : CO2 seulement."),
        ] = None,
        litres: Annotated[float, Field(gt=0, le=500, description="Volume du plein.")] = 40.0,
    ) -> ReponseComparaison:
        with relayer():
            comparaison = await client.obtenir("/empreinte/comparaison", litres=litres)
            prix_locaux: dict[str, dict[str, Any]] = {}
            nom_lieu: str | None = None
            if lieu and lieu.strip():
                place = await geocoder(client, lieu)
                nom_lieu = place.libelle
                autour = await client.obtenir(
                    "/stations/proches",
                    lat=place.latitude,
                    lon=place.longitude,
                    rayon_km=10,
                    tri="prix",
                    limite=200,
                )
                for station in autour.get("stations", []):
                    for prix in station.get("prix", []):
                        code = str(prix["carburant"])
                        valeur = prix.get("prix_eur_l")
                        if not valeur:
                            continue
                        ancien = prix_locaux.get(code)
                        if ancien is None or float(valeur) < float(ancien["prix_eur_l"]):
                            prix_locaux[code] = {
                                "prix_eur_l": float(valeur),
                                "station_id": station["id"],
                                "ville": station.get("ville"),
                                "maj": prix.get("maj"),
                            }

        co2_par_code = {e["carburant"]: e for e in comparaison.get("empreintes", [])}
        carburants = []
        for code in CODES:
            empreinte = co2_par_code.get(code)
            local = prix_locaux.get(code)
            entree: dict[str, Any] = {
                "carburant": code,
                "carburant_libelle": libelle(code),
                "co2_kg_du_plein": empreinte["co2_kg"] if empreinte else None,
                "facteur_kg_co2e_par_litre": (
                    empreinte["facteur_kg_co2e_par_litre"] if empreinte else None
                ),
            }
            if local:
                entree["prix_le_moins_cher_eur_l"] = local["prix_eur_l"]
                entree["prix_affiche"] = prix_litre(local["prix_eur_l"])
                entree["cout_du_plein_eur"] = round(local["prix_eur_l"] * litres, 2)
                entree["station_id"] = local["station_id"]
                entree["ville"] = local["ville"]
                entree["maj"] = local["maj"]
            elif nom_lieu:
                entree["prix_le_moins_cher_eur_l"] = None
                entree["indisponible_sur_place"] = True
            carburants.append(entree)

        lignes = []
        for entree in carburants:
            morceaux = [f"{entree['carburant_libelle']} :"]
            if entree.get("prix_affiche"):
                morceaux.append(str(entree["prix_affiche"]))
                morceaux.append(f"({nombre(float(entree['cout_du_plein_eur']), 2)} € le plein)")
            elif entree.get("indisponible_sur_place"):
                morceaux.append("non trouve dans les 10 km")
            if entree.get("co2_kg_du_plein") is not None:
                morceaux.append(f"— {co2_kg(float(entree['co2_kg_du_plein']))}")
            lignes.append("- " + " ".join(morceaux))

        entete = f"Comparaison pour un plein de {litres_affiches(litres)}"
        entete += f" autour de {nom_lieu} :" if nom_lieu else " (CO2 seulement) :"
        avertissement = str(comparaison.get("avertissement", ""))
        texte = entete + "\n" + "\n".join(lignes) + "\n" + avertissement

        return ReponseComparaison(
            lieu=nom_lieu,
            litres=litres,
            carburants=carburants,
            avertissement=avertissement,
            source_co2=str(comparaison.get("source", "ADEME, Base Carbone")),
            texte=texte,
        )
