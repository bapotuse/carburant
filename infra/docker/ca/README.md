# Certificats d'autorité supplémentaires

Ce dossier est copié dans les images et son contenu est ajouté au magasin de
certificats du système à la construction.

Il est **vide en temps normal** et doit le rester dans le dépôt. Il n'existe que pour
les environnements de construction placés derrière un proxy qui termine le TLS : on y
dépose alors le `.crt` de l'autorité du proxy, et la construction aboutit sans toucher
au Dockerfile ni désactiver la vérification TLS.

Les fichiers `.crt` déposés ici sont ignorés par git.
