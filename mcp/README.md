# prix-carburant-mcp

Serveur MCP qui donne les prix des carburants en France, à votre assistant.

« Où est l'essence la moins chère près de moi ? Je suis au Prado à Marseille. »
« Il me reste 20 km d'autonomie, où faire le plein ? »
« Le gazole a-t-il baissé ce mois-ci dans les Bouches-du-Rhône ? »

Les prix viennent du flux officiel du gouvernement, mis à jour **toutes les quinze
minutes** : les quelque 9 800 stations de France métropolitaine et de Corse, six
carburants, et vingt ans d'historique depuis 2007.

## Installer

### Le connecteur distant, sans rien installer

Ajoutez cette adresse comme serveur MCP distant dans votre client :

```
https://carburant.144-24-195-97.sslip.io/mcp
```

Transport Streamable HTTP, sans état, sans authentification. C'est le plus simple, et
il n'y a rien à mettre à jour.

### En local, avec uvx

```bash
uvx --from "git+https://github.com/bapotuse/carburant#subdirectory=mcp" prix-carburant-mcp
```

Le serveur appelle l'API publique du projet ; il n'a besoin d'aucune base de données
ni d'aucune clé.

### Claude Code

```bash
claude mcp add carburant -- uvx --from "git+https://github.com/bapotuse/carburant#subdirectory=mcp" prix-carburant-mcp
```

Ou, pour le connecteur distant :

```bash
claude mcp add --transport http carburant https://carburant.144-24-195-97.sslip.io/mcp
```

### Claude Desktop, et les autres clients en stdio

Dans `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "carburant": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/bapotuse/carburant#subdirectory=mcp",
        "prix-carburant-mcp"
      ]
    }
  }
}
```

### Pointer sur une autre API

```bash
CARBURANT_API_BASE=http://localhost:8000/v1 prix-carburant-mcp
```

| Variable | Rôle | Défaut |
|---|---|---|
| `CARBURANT_API_BASE` | URL de base de l'API | la production du projet |
| `CARBURANT_MCP_HOTES` | en-têtes `Host` acceptés par le transport HTTP | le domaine public et la boucle locale |
| `CARBURANT_MCP_LOG` | niveau de journalisation | `INFO` |

## Les six outils

| Outil | Quand il sert |
|---|---|
| `trouver_station_moins_chere` | « où est l'essence la moins chère près de… ? » |
| `meilleure_station_avec_autonomie` | dès qu'il est question d'autonomie restante : le coût du détour change la réponse |
| `prix_station` | une station précise, par son identifiant ou son adresse |
| `tendance_prix` | « le gazole a-t-il baissé ce mois-ci ? », national ou par département |
| `empreinte_carbone_plein` | le CO2 d'un plein, avec sa source ADEME complète |
| `comparer_carburants` | « essence ou diesel ? », prix locaux et CO2 côte à côte |

Tous sont annotés **en lecture seule** : ils n'écrivent rien, nulle part.

## Trois règles que le serveur impose à l'assistant

Elles sont dans les instructions transmises au client, et c'est ce qui distingue ce
serveur d'un simple passe-plat.

1. **Un prix ne s'énonce jamais sans sa date.** Chaque réponse porte l'âge du prix
   (« il y a 2 heures »). « L'essence est à 1,75 € » devient faux en silence ;
   « 1,75 €, relevé il y a deux heures » reste vrai pour toujours.
2. **Une adresse ambiguë se fait préciser, jamais deviner.** L'avenue du Prado existe
   en 13006 et en 13008, à un kilomètre l'une de l'autre, sans aucune station en
   commun. Le serveur refuse et liste les candidats.
3. **Un chiffre de CO2 sort avec sa source**, ou ne sort pas. Si aucun facteur
   d'émission n'est chargé, l'outil refuse plutôt que d'estimer.

Même chose pour les carburants : « diesel », « sans plomb 95 », « E10 » et « GPL »
sont compris, mais **« super » et « essence » sont refusés** — ils désignent plusieurs
carburants, et deviner afficherait un prix faux sans le dire.

## Ce que ces données ne contiennent pas

- **Aucune station d'outre-mer** : le flux officiel n'en publie pas.
- **Aucun nom de station** : le flux ne contient ni nom ni enseigne. Les enseignes
  viennent d'OpenStreetMap, qui en couvre 99,4 %. Une station sans enseigne connue
  s'identifie par son adresse.
- **Tous les carburants ne sont pas partout** : mesuré sur les 9 825 stations actives,
  le gazole a un prix dans 97 % d'entre elles, le SP98 et l'E10 dans 78 %, l'E85 dans
  40 %, le SP95 dans 29 % et le GPL dans 15 %. Un carburant absent d'une réponse n'est
  pas gratuit : il est introuvable sur place.
- **Le coût réel d'un détour repose sur trois hypothèses**, rendues avec le résultat :
  aller-retour depuis la position, carburant du trajet valorisé au prix de la station,
  distance routière estimée à partir de la distance à vol d'oiseau.

## Sources et licences

| Donnée | Source | Licence |
|---|---|---|
| Prix et stations | [Prix des carburants, flux instantané v2](https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/) | Licence Ouverte 2.0 (Etalab) |
| Enseignes | [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL — © les contributeurs d'OpenStreetMap |
| Facteurs d'émission | [Base Carbone®, ADEME](https://data.ademe.fr/datasets/base-carbone(r)) | Licence Ouverte 2.0 |
| Géocodage | [Géoplateforme, IGN](https://data.geopf.fr/geocodage/search) | Licence Ouverte 2.0 |

## Développer

```bash
uv sync --all-packages
uv run prix-carburant-mcp --verifier          # assemble le serveur et liste ses outils
uv run pytest mcp/tests                       # 73 tests, dont 21 par le vrai protocole
```

Le serveur n'ouvre **jamais** la base de données : il appelle l'API publique, comme
n'importe quel visiteur du site. C'est ce qui permet de l'installer sans rien héberger,
et ce qui garantit qu'un assistant voit exactement les mêmes chiffres que le site.
