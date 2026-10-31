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

## Liste de dépôts (upload `.txt` / `.csv` ou copier-coller)

Un dépôt par ligne ; les autres mots de la ligne deviennent le nom affiché. Lignes invalides signalées.

```
jean.dupont, https://github.com/my-org/day06-jean.dupont
git@github.com:my-org/day06-marie.curie.git
github.com/my-org/day06-alan.turing
```

Dépôts privés : soit `AGORA_GITHUB_TOKEN` (URLs https), soit une clé SSH de l'utilisateur `agora`
ajoutée à ton compte GitHub (URLs `git@`).

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
