"""Marqueur de paquet, et il n'est pas decoratif.

Sans lui, pytest nomme les modules de test `mcp.tests.test_...` : il importe donc
`mcp` comme paquet-espace de noms depuis la racine du depot, ce qui fait pointer
`sys.modules['mcp']` sur `/home/user/mcp` et **masque le SDK** `mcp` pour tout le
reste de la session. Le symptome est deroutant : « No module named 'mcp.server' »
alors que le SDK est installe et que `python -c "import mcp.server"` fonctionne.

Avec ce fichier, pytest remonte jusqu'a `mcp/` (qui n'a pas de `__init__.py`), nomme
les modules `tests.test_...` et insere `/home/user/mcp` dans `sys.path` -- un
repertoire qui ne contient aucun dossier `mcp`. Le SDK est alors trouve normalement.

C'est l'autre moitie de la regle de `docs/specs/api-mcp.md` : « le dossier `mcp/` ne
doit jamais etre lui-meme importable ». Le layout `src/` ne suffit pas ; il faut aussi
empecher pytest de le traiter comme une racine de paquet.
"""
