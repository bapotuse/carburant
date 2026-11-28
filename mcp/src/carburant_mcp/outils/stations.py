"""Les trois outils qui répondent à « où faire le plein ? ».

Les descriptions sont écrites pour un modèle de langage, pas pour un humain qui lit
une documentation : elles disent **quand** choisir cet outil plutôt qu'un autre, ce
que valent les unités, et ce que la réponse contient. Un outil mal décrit est un outil
appelé au mauvais moment, et la réponse paraîtra fausse alors qu'elle sera juste.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from carburant_mcp.carburants import libelle, normaliser
from carburant_mcp.client import ClientCarburant
from carburant_mcp.erreurs import relayer
from carburant_mcp.formats import euros
from carburant_mcp.lieux import geocoder
from carburant_mcp.presentation import StationLisible, decrire, lire_station, nommer

LECTURE_SEULE = ToolAnnotations(read_only_hint=True, open_world_hint=True)
"""Ces outils lisent une API publique et ne modifient rien.

`open_world_hint` est vrai parce que les prix changent toutes les quinze minutes : deux
appels identiques peuvent légitimement donner deux réponses.
"""

STATIONS_RENDUES = 5
"""Combien de stations on rend. Une liste de vingt serait illisible à l'oral, et le
modèle n'en citerait que les premières de toute façon."""


class ReponseStations(BaseModel):
    """Les stations les moins chères autour d'un lieu."""

    lieu: str = Field(description="Le lieu tel que le geocodeur l'a comprise.")
    carburant: str = Field(description="Code du carburant retenu.")
    carburant_libelle: str
    rayon_km: float
    stations: list[StationLisible] = Field(
        description="Les moins cheres d'abord. Vide si aucune station ne vend ce carburant."
    )
    total_dans_le_rayon: int = Field(description="Stations trouvees avant de n'en garder que cinq.")
    texte: str = Field(description="La reponse en une phrase ou deux, prete a etre lue.")


class ReponseAutonomie(BaseModel):
    """La meilleure station compte tenu du coût réel, détour compris."""

    lieu: str
    carburant: str
    carburant_libelle: str
    autonomie_km: float
    meilleure: StationLisible | None = None
    la_plus_proche: StationLisible | None = Field(
        default=None, description="Ce que ferait quelqu'un qui ne calcule pas. Sert de reference."
    )
    economie_eur: float = Field(
        default=0.0, description="Ce qu'on gagne a aller a la meilleure plutot qu'a la plus proche."
    )
    economie_affichee: str = Field(default="")
    stations: list[StationLisible] = Field(default_factory=list)
    atteignables: int = 0
    hypotheses: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Ce que le calcul suppose : aller-retour, facteur de detour, marge "
            "d'autonomie, volume et consommation retenus. A citer si l'utilisateur "
            "demande d'ou sort le chiffre."
        ),
    )
    avertissement: str | None = None
    texte: str


class ReponsePrixStation(BaseModel):
    """Tous les prix d'une station, ruptures et prix périmés compris."""

    id: int
    enseigne: str | None = None
    adresse: str | None = None
    ville: str | None = None
    code_postal: str | None = None
    autoroute: bool = False
    prix: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Un element par carburant : code, libelle, prix, date, fraicheur, et "
            "`rupture` quand la station annonce le carburant sans en avoir."
        ),
    )
    distance_de_l_adresse_km: float | None = Field(
        default=None,
        description=(
            "Rempli seulement quand la station a ete trouvee par une adresse et non "
            "par son identifiant. Si cette distance est grande, c'est que l'adresse "
            "ne designait pas cette station : il faut le dire."
        ),
    )
    texte: str


def _maintenant() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _texte_stations(reponse: ReponseStations) -> str:
    if not reponse.stations:
        return (
            f"Aucune station ne vend du {reponse.carburant_libelle} dans un rayon de "
            f"{reponse.rayon_km:g} km autour de {reponse.lieu}. Essaie un rayon plus "
            "large, ou un autre carburant."
        )
    lignes = [decrire(station) for station in reponse.stations]
    entete = (
        f"{reponse.carburant_libelle.capitalize()} autour de {reponse.lieu} — "
        f"{reponse.total_dans_le_rayon} station"
        f"{'s' if reponse.total_dans_le_rayon > 1 else ''} dans "
        f"{reponse.rayon_km:g} km, les moins cheres :"
    )
    return entete + "\n" + "\n".join(f"- {ligne}" for ligne in lignes)


def enregistrer(serveur: MCPServer[Any], client: ClientCarburant) -> None:
    """Déclare les trois outils sur le serveur."""

    @serveur.tool(
        name="trouver_station_moins_chere",
        title="Station la moins chère près d'un lieu",
        description=(
            "Les stations les moins cheres autour d'un lieu, pour un carburant.\n\n"
            "**Choisis cet outil** quand la question est « ou est l'essence la moins "
            "chere pres de moi ? » ou « combien coute le gazole a tel endroit ? ». Si "
            "l'utilisateur donne une autonomie restante, prefere "
            "`meilleure_station_avec_autonomie`, qui compte le cout du detour.\n\n"
            "`lieu` est du texte libre : « le Prado a Marseille », « 40 avenue du "
            "Prado, 13006 Marseille », « 13008 ». Si l'adresse est ambigue, l'outil "
            "refuse et liste les candidats : demande alors lequel, ne choisis pas.\n\n"
            "`carburant` accepte les synonymes courants (« diesel », « sans plomb 95 », "
            "« E10 », « GPL »). « Super » et « essence » sont refuses parce qu'ils "
            "designent plusieurs carburants.\n\n"
            "La reponse donne au plus cinq stations, les moins cheres d'abord, chacune "
            "avec son prix, **la date du prix**, la distance et des liens d'itineraire. "
            "Cite toujours la date : un prix sans sa date devient faux en silence."
        ),
        annotations=LECTURE_SEULE,
    )
    async def trouver_station_moins_chere(
        lieu: Annotated[str, Field(description="Adresse, quartier, ville ou code postal.")],
        carburant: Annotated[str, Field(description="Carburant voulu, synonymes acceptes.")],
        rayon_km: Annotated[
            float, Field(gt=0, le=50, description="Rayon de recherche en kilometres.")
        ] = 5.0,
    ) -> ReponseStations:
        with relayer():
            code = normaliser(carburant)
            place = await geocoder(client, lieu)
            brut = await client.obtenir(
                "/stations/proches",
                lat=place.latitude,
                lon=place.longitude,
                carburant=code,
                rayon_km=rayon_km,
                tri="prix",
                limite=STATIONS_RENDUES,
            )

        maintenant = _maintenant()
        stations = [
            lire_station(station, prix, maintenant=maintenant)
            for station in brut.get("stations", [])
            for prix in station.get("prix", [])
            if prix.get("carburant") == code and prix.get("prix_eur_l")
        ]
        reponse = ReponseStations(
            lieu=place.libelle,
            carburant=code,
            carburant_libelle=libelle(code),
            rayon_km=rayon_km,
            stations=stations[:STATIONS_RENDUES],
            total_dans_le_rayon=int(brut.get("total", len(stations))),
            texte="",
        )
        reponse.texte = _texte_stations(reponse)
        return reponse

    @serveur.tool(
        name="meilleure_station_avec_autonomie",
        title="Meilleure station avec une autonomie limitée",
        description=(
            "La station au **cout reel le plus bas**, detour compris, parmi celles "
            "qu'on peut encore atteindre.\n\n"
            "**Choisis cet outil** des que l'utilisateur parle d'autonomie, de reserve, "
            "de « il me reste X km », ou demande si un detour vaut le coup. C'est la "
            "question que `trouver_station_moins_chere` ne sait pas trancher : la "
            "station la moins chere n'est pas toujours la moins chere, parce qu'y aller "
            "consomme du carburant.\n\n"
            "Le cout reel vaut `prix x litres + prix x (2 x distance x consommation / "
            "100)`. La reponse porte le champ `hypotheses` : aller-retour depuis la "
            "position, carburant du trajet valorise au prix de la station, distance "
            "routiere **estimee** a partir de la distance a vol d'oiseau. Cite ces "
            "hypotheses si on te demande d'ou sort le chiffre, et ne presente jamais le "
            "cout comme exact.\n\n"
            "Une marge de securite de 20 % est appliquee a l'autonomie annoncee : on ne "
            "recommande pas une station a l'exacte limite du reservoir. Si rien n'est "
            "atteignable, la reponse le dit dans `avertissement` — relaie-le, ne propose "
            "pas une station hors de portee."
        ),
        annotations=LECTURE_SEULE,
    )
    async def meilleure_station_avec_autonomie(
        lieu: Annotated[str, Field(description="Position de depart, en texte libre.")],
        carburant: Annotated[str, Field(description="Carburant voulu, synonymes acceptes.")],
        autonomie_km: Annotated[
            float,
            Field(
                gt=0, le=1500, description="Kilometres restants annonces par le tableau de bord."
            ),
        ],
        litres: Annotated[
            float | None,
            Field(
                default=None,
                gt=0,
                le=500,
                description="Volume du plein. Par defaut 40 L, une valeur d'exemple et non une moyenne mesuree.",
            ),
        ] = None,
    ) -> ReponseAutonomie:
        with relayer():
            code = normaliser(carburant)
            place = await geocoder(client, lieu)
            brut = await client.obtenir(
                "/stations/meilleure",
                lat=place.latitude,
                lon=place.longitude,
                carburant=code,
                autonomie_km=autonomie_km,
                litres=litres,
            )

        maintenant = _maintenant()

        def lire(entree: dict[str, Any] | None) -> StationLisible | None:
            if not entree:
                return None
            prix = {
                "carburant": code,
                "prix_eur_l": entree["prix_eur_l"],
                "maj": entree.get("maj"),
            }
            return lire_station(entree, prix, maintenant=maintenant)

        meilleure = lire(brut.get("meilleure"))
        plus_proche = lire(brut.get("la_plus_proche"))
        economie = float(brut.get("economie_eur") or 0.0)

        if meilleure is None:
            texte = brut.get("avertissement") or (
                f"Aucune station de {libelle(code)} n'est atteignable avec "
                f"{autonomie_km:g} km d'autonomie autour de {place.libelle}."
            )
        else:
            cout = float(brut["meilleure"]["cout_reel_eur"])
            texte = (
                f"{nommer(meilleure)} — {meilleure.prix_affiche}"
                + (f" ({meilleure.maj_affichee})" if meilleure.maj_affichee else "")
                + f", a {meilleure.distance_affichee}. Plein estime a {euros(cout)}, "
                "detour aller-retour compris."
            )
            if economie > 0 and plus_proche is not None:
                texte += (
                    f" Soit {euros(economie)} de moins qu'en allant a la plus proche "
                    f"({nommer(plus_proche)}, {plus_proche.prix_affiche})."
                )
            elif plus_proche is not None and plus_proche.id == meilleure.id:
                texte += " C'est aussi la plus proche : il n'y a rien a gagner ailleurs."
            if meilleure.prix_date_de_plus_de_24h:
                texte += " Attention, ce prix a plus de 24 h."

        return ReponseAutonomie(
            lieu=place.libelle,
            carburant=code,
            carburant_libelle=libelle(code),
            autonomie_km=autonomie_km,
            meilleure=meilleure,
            la_plus_proche=plus_proche,
            economie_eur=economie,
            economie_affichee=euros(economie) if economie > 0 else "",
            stations=[
                station
                for station in (lire(entree) for entree in brut.get("stations", []))
                if station is not None
            ][:STATIONS_RENDUES],
            atteignables=int(brut.get("atteignables") or 0),
            hypotheses=brut.get("hypotheses") or {},
            avertissement=brut.get("avertissement"),
            texte=texte,
        )

    @serveur.tool(
        name="prix_station",
        title="Tous les prix d'une station",
        description=(
            "Tous les carburants d'une seule station, avec leurs prix et leurs dates.\n\n"
            "**Choisis cet outil** quand l'utilisateur designe une station precise : "
            "« et a la station Total du boulevard Michelet ? », « combien coute le "
            "gazole a la 13008003 ? ». Pour chercher autour d'un lieu, prends "
            "`trouver_station_moins_chere`.\n\n"
            "`station` accepte un identifiant officiel (que des chiffres) ou une "
            "adresse. Avec une adresse, l'outil prend la station **la plus proche** et "
            "rend `distance_de_l_adresse_km` : si cette distance depasse quelques "
            "centaines de metres, dis-le, parce que ce n'est probablement pas la "
            "station voulue.\n\n"
            "Contrairement a une recherche, cette reponse **ne cache rien** : les prix "
            "perimes y figurent avec leur date, et les carburants en rupture sont "
            "marques comme tels. Ne presente pas un prix perime comme le prix du jour."
        ),
        annotations=LECTURE_SEULE,
    )
    async def prix_station(
        station: Annotated[
            str, Field(description="Identifiant officiel (chiffres) ou adresse de la station.")
        ],
    ) -> ReponsePrixStation:
        texte_station = station.strip()
        distance: float | None = None
        with relayer():
            if texte_station.isdigit():
                fiche = await client.obtenir(f"/stations/{int(texte_station)}")
            else:
                place = await geocoder(client, texte_station)
                autour = await client.obtenir(
                    "/stations/proches",
                    lat=place.latitude,
                    lon=place.longitude,
                    rayon_km=2,
                    tri="distance",
                    limite=1,
                )
                proches = autour.get("stations") or []
                if not proches:
                    from carburant_mcp.client import ErreurAPI

                    raise ErreurAPI(
                        f"Aucune station a moins de 2 km de « {texte_station} ». Donne "
                        "une adresse plus proche d'une station, ou son identifiant."
                    )
                distance = float(proches[0]["distance_km"])
                fiche = await client.obtenir(f"/stations/{int(proches[0]['id'])}")

        maintenant = _maintenant()
        prix = []
        for entree in fiche.get("prix", []):
            code = str(entree["carburant"])
            lisible = {
                "carburant": code,
                "carburant_libelle": libelle(code),
                "prix_eur_l": entree.get("prix_eur_l"),
                "fraicheur": entree.get("fraicheur"),
                "maj": entree.get("maj"),
                "rupture": entree.get("rupture"),
            }
            if entree.get("prix_eur_l") and entree.get("maj"):
                faux = {"carburant": code, "prix_eur_l": entree["prix_eur_l"], "maj": entree["maj"]}
                vue = lire_station({**fiche, "distance_km": 0.0}, faux, maintenant=maintenant)
                lisible["prix_affiche"] = vue.prix_affiche
                lisible["maj_affichee"] = vue.maj_affichee
            prix.append(lisible)

        nom = fiche.get("enseigne") or fiche.get("adresse") or f"station {fiche['id']}"
        lignes = []
        for entree in prix:
            if entree.get("rupture"):
                lignes.append(f"- {entree['carburant_libelle']} : en rupture")
            elif entree.get("prix_affiche"):
                suffixe = f" ({entree['maj_affichee']})" if entree.get("maj_affichee") else ""
                alerte = " ⚠ prix perime" if entree.get("fraicheur") == "perime" else ""
                lignes.append(
                    f"- {entree['carburant_libelle']} : {entree['prix_affiche']}/L{suffixe}{alerte}"
                )
        entete = f"{nom}"
        if fiche.get("ville"):
            entete += f", {fiche['ville']}"
        if distance is not None:
            entete += f" (station la plus proche de l'adresse donnee, a {distance:.1f} km)"
        texte = entete + "\n" + ("\n".join(lignes) if lignes else "- aucun prix connu")

        return ReponsePrixStation(
            id=int(fiche["id"]),
            enseigne=fiche.get("enseigne"),
            adresse=fiche.get("adresse"),
            ville=fiche.get("ville"),
            code_postal=fiche.get("cp"),
            autoroute=bool(fiche.get("autoroute", False)),
            prix=prix,
            distance_de_l_adresse_km=distance,
            texte=texte,
        )
