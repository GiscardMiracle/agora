# Agora

Mini-Jenkins pour évaluer les projets des étudiants pendant les soutenances.
Un **job** = un set de tests (fichiers + commande). On y ajoute des dépôts GitHub (upload d'une liste),
on lance un dépôt ou tous, et la sortie s'affiche en direct comme dans un terminal. Historique conservé.

```
FastAPI (1 process) ── SQLite (data/agora.db)
   │  workers asyncio (AGORA_WORKERS)
   ├─ git clone --depth 1      (sur l'hôte, token jamais écrit sur disque)
   └─ docker run agora-runner  (--network none, RAM/CPU/PIDs limités, user non-root)
        /work  = dépôt de l'étudiant (dossier courant)
        /tests = fichiers du job (lecture seule)
   └─ sortie (pseudo-TTY) → data/logs/<build>.log → UI (polling incrémental)
```

## Écrire un set de tests

- Les fichiers du job (ex. `tests.sh`, `main.c`) sont montés dans `/tests`, le dépôt dans `/work`.
- La commande par défaut est `bash /tests/tests.sh`. Code de sortie `0` = ✅, sinon ❌.
- Pas de réseau. On écrit dans `/work` ou `/tmp`. Stdin = `/dev/null` (passer les entrées par pipe).
- Afficher `AGORA_SCORE: 7/10` remplit la colonne *Score* (la dernière occurrence gagne).
- Modèles prêts à l'emploi :
  - [`examples/myprintf/`](examples/myprintf) : my_printf (Makefile, relink, fonctions interdites via `nm`,
    119 appels `my_printf` comparés octet par octet au vrai `printf`, retour et `%n` compris).
    Chaque test affiche l'appel C exact, la sortie attendue/obtenue façon `cat -e` et la valeur de retour.
    Ajouter un test = une ligne `CASE("section", my_printf(...))` dans `main.c`. Timeout conseillé : 180 s.
  - [`examples/101pong/`](examples/101pong) : programme en langage libre (C/C++, Python, bash, ou tout ce que contient l'image).
    Makefile si présent, `-h`, exemples du sujet, impact sur la raquette, précision, cas aléatoires, erreurs (exit 84, stderr).
    Sorties attendues calculées par `ref.py`. Uploader `tests.sh` et `ref.py`. Timeout conseillé : 300 s.
  - [`examples/c-functions/`](examples/c-functions) : compile `main.c` avec des fichiers de l'étudiant (exercices de fonctions C).

## Liste de dépôts

Un dépôt par ligne ; les autres mots de la ligne deviennent le nom affiché. Lignes invalides signalées.

```
jean.dupont, https://github.com/my-org/day06-jean.dupont
git@github.com:my-org/day06-marie.curie.git
github.com/my-org/day06-alan.turing
```

### Depuis GitHub (bouton *add repositories*)

Dans l'onglet *Dépôts* d'un job, renseigne l'organisation et un pattern (glob `day06-*`, ou `re:` + regex).
*add repositories* crée la liste ; le même bouton (*update repositories*) la met à jour : nouveaux dépôts ajoutés,
dépôts disparus retirés. Un pattern qui ne trouve rien ne modifie jamais la liste.
Chaque groupe est nommé d'après les emails des auteurs des commits (filtrés par `AGORA_EMAIL_DOMAIN`), ou d'après le
numéro du dépôt s'il n'y a aucun commit. Le crayon ✎ renomme à la main ; un nom modifié n'est plus jamais écrasé.
Nécessite `AGORA_GITHUB_TOKEN` (lecture seule) pour interroger l'API.

### Clonage : une clé SSH par correcteur

Les dépôts sont clonés **en SSH avec la clé du compte qui lance le build** (URLs converties en `git@github.com:`).
Chaque utilisateur génère sa clé dans *mon compte* (la clé privée reste dans `data/keys/`, mode 0600) puis ajoute la
clé publique sur GitHub. Sans clé, lancer un job renvoie une erreur immédiate. Supprimer un compte supprime sa clé.

### Limite de lancements

Chaque non-admin dispose de 15 lancements **au total** (ajustable par l'admin dans *Utilisateurs*, compteur
remis à zéro avec ↺). Un lancement = un clic sur ▶ (dépôt seul, tout, ou filtre), quel que soit le nombre de dépôts.

## Analyse des résultats

- **Tri et filtres** : la liste des dépôts se filtre par texte et par statut (en échec, réussis, en cours, jamais lancés) et se trie
  (nom, score, statut, date, durée). *Run shown* ne lance que les dépôts affichés : filtre sur « failing » pour relancer les échecs.
- **Tests en échec** : une ligne `✘ libellé` dans la sortie est un test raté, une ligne `━━ nom` ouvre une section (c'est ce que
  fait le `record` des exemples). Les échecs sont listés sur la page du build, et l'onglet *Failures* d'un job classe les tests
  par nombre d'étudiants qui les ratent, avec la liste des noms.
- **Notes** : l'icône note d'une ligne enregistre un commentaire libre sur un dépôt (remarques de soutenance), exporté dans le CSV.
- **Similarité** : à chaque clone, les sources sont réduites à une empreinte (noms de variables, nombres, chaînes et commentaires
  sont ignorés, puis hachage par fenêtres de 7 tokens et *winnowing*). L'onglet *Similarity* liste les paires qui partagent une
  grande part de leur code. Le code commun à au moins un quart de la classe (squelette fourni) est ignoré.
  Un score élevé dit « lis les deux », pas « triche ».
- **Coding style** : les rapports de `banana-check-repo` (`fichier:ligne: MAJOR:C-F3`) et les diagnostics clang qui portent un
  identifiant de règle (`... warning: ... [C-G1]`) sont comptés par gravité. La colonne *Style* affiche `major / minor / info`,
  le CSV aussi. Rien à écrire dans le test : il suffit que la commande du checker s'exécute dans le conteneur (voir ci-dessous).

### Style et mémoire : à mettre dans `tests.sh`

Le checker doit exister dans l'image (`runner/Dockerfile`, `COPY` du binaire `banana-check-repo` et du dossier des plugins
`epiclang` dans `/usr/local/lib/epiclang/plugins`). Ensuite, dans le test :

```bash
# coding style : la sortie du checker est comptée par Agora, aucun parsing à faire ici
banana-check-repo . 2>&1 | sed 's/^/    /'
find . -name '*.c' -exec epiclang -fsyntax-only -I include {} + 2>&1

# fuites et accès invalides : valgrind rend le code 42 s'il trouve quelque chose
valgrind -q --leak-check=full --error-exitcode=42 ./mon_programme args >/dev/null 2>/tmp/vg
[ $? -eq 42 ] && record memory 1 "valgrind" "$(head -5 /tmp/vg)" || record memory 0 "valgrind"
```

## Planification

Onglet *Settings* d'un job (propriétaire uniquement), carte *scheduled runs* : lance tous les dépôts **une fois** à une date
(rendu à une échéance) ou **de façon récurrente** avec une expression cron à 5 champs (`minute heure jour-du-mois mois jour-de-semaine`,
listes, plages, pas `*/15`, `@daily`…). Quand jour du mois et jour de semaine sont tous deux fixés, l'un **ou** l'autre suffit (cron standard).
Le fuseau est `AGORA_TZ` (ex. `Europe/Paris`), sinon l'heure du serveur. Un passage manqué de plus de 15 minutes (serveur éteint)
est ignoré et signalé plutôt que lancé en retard. Les passages planifiés utilisent ta clé SSH et ne consomment pas ta limite de lancements.

## Visibilité et partage

Un job (et les dossiers créés) n'est visible que de son créateur et des admins. Dans *Settings → sharing*, le créateur
choisit qui d'autre peut le voir. Les personnes avec qui il est partagé consultent les résultats et lancent des builds
(avec leur propre clé SSH et leur propre quota) ; seuls le créateur et les admins modifient, partagent ou suppriment.
Quand un compte est supprimé, ses jobs passent à l'admin qui le supprime.

## Archives et purge

*⤓ archive* exporte tout l'historique d'un job en ZIP (`builds.csv` + `logs/<dépôt>/<build>.log`).
Les builds terminés de plus de `AGORA_RETENTION_DAYS` (90) jours sont supprimés automatiquement, logs compris.

## Dossiers

Les jobs peuvent être rangés dans des dossiers imbriqués (`C/week-1`) : créer un dossier depuis la liste,
ou renseigner le champ *Dossier* dans les paramètres d'un job. ✎ renomme/déplace un dossier, ✕ le supprime (s'il est vide).

## Thème

Bouton ☀/☾ en haut à droite (clair / sombre, mémorisé dans le navigateur).

## Comptes

Pas d'inscription : seul un admin crée les comptes (menu *utilisateurs*).

| Rôle | Droits |
|------|--------|
| admin | tout, y compris les comptes |
| correcteur | jobs, fichiers de test, dépôts, lancements |
| lecteur | consultation seule (résultats, logs, fichiers de test) |

Au premier démarrage, si aucun compte n'existe, l'admin est créé avec `AGORA_ADMIN_USER` (défaut `admin`) et `AGORA_PASSWORD`.
Ces variables ne servent plus ensuite ; les comptes vivent dans la base.

Mot de passe perdu : `cd /opt/agora && sudo -u agora .venv/bin/python -m app.users <nom>` (crée un admin si le nom n'existe pas).

Un correcteur peut ajouter tout dépôt accessible au token ou à la clé SSH du serveur et en lire le contenu via les logs.

## Raccourcis

- Page d'un build : `←` / `→` étudiant précédent/suivant, `r` relancer.
- Liste des dépôts : `/` pour filtrer.

## Déploiement (Ubuntu)

```sh
sudo git clone <ce-repo> /opt/agora && cd /opt/agora
sudo bash deploy/install.sh          # docker, uv, image sandbox, service systemd, .env (mot de passe généré)
sudo nano /opt/agora/.env            # AGORA_GITHUB_TOKEN, AGORA_HTTPS=1 si HTTPS
sudo systemctl restart agora
```

Puis un reverse proxy : `sudo apt install caddy` et [`deploy/Caddyfile`](deploy/Caddyfile)
dans `/etc/caddy/Caddyfile` (HTTPS automatique si tu as un domaine). Ouvrir 80/443 dans le
security group AWS.

Mise à jour : `cd /opt/agora && sudo -u agora git pull && sudo -u agora ~agora/.local/bin/uv sync && sudo systemctl restart agora`.

Logs : `journalctl -u agora -f`. Sauvegarde : le dossier `data/`.

## Dev local

```sh
uv sync
docker build -t agora-runner:latest runner/
AGORA_PASSWORD=dev uv run uvicorn app.main:app --reload --port 8080
```

## Ressources

Pensé pour un VPS 2 Go / 10 Go : 2 builds en parallèle × 512 Mo max, image sandbox ~1,15 Go (gcc + clang),
clones supprimés après chaque build, 20 builds gardés par dépôt, logs plafonnés à 2 Mo.
