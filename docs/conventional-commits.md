# Conventional Commits

Wszystkie commity **muszą** spełniać [Conventional Commits 1.0](https://www.conventionalcommits.org/).

## Format

```
<type>[scope][!]: <opis>
```

- `type` — jeden z: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- `scope` — opcjonalny, bez spacji/nawiasów. Dla tego repo:
  `core`, `tui`, `cli`, `gui`, `docker`, `tunnel`, `k8s`, `mcp`, `docs`, `ci`, `repo`.
- `!` — opcjonalnie przed dwukropkiem, oznacza breaking change.
- `opis` — po spacji, małą literą, bez kropki na końcu, max ~100 znaków.

## Przykłady

```bash
feat(tui): dodaj sortowanie tabeli po porcie
fix(docker): popraw parsowanie mapowania IPv6 w Ports
docs: dopisz decyzję o braku Dockera w devie
refactor(core)!: zmień PortEntry na frozen dataclass
chore(repo): dodaj hook conventional commits
```

Breaking change opisuj też w stopce (`BREAKING CHANGE: ...`), ale samo `!` wystarcza do zaliczenia hooka.

## Egzekwowanie

1. **Lokalnie — lefthook**
   Hook `commit-msg` z `lefthook.yml` wywołuje `scripts/check_commit_msg.py`
   (czysty stdlib, ten sam regex co wcześniej, działa na Win/Mac/Linux).

   Po klonie repo wykonaj raz:

   ```bash
   # najpierw sam lefthook (jedno z):
   brew install lefthook                # macOS
   winget install evilmartians.lefthook  # Windows
   uv tool install lefthook              # dowolny OS

   # potem podpięcie hooków w tym repo:
   lefthook install
   ```

   Zły format = commit odrzucony z podpowiedzią. Awaryjnie (tylko lokalnie):
   `git commit --no-verify` — ale push i tak zablokuje ruleset (pkt 2).
   Nie ustawiaj ręcznie `git config core.hooksPath` — lefthook zarządza
   `.git/hooks` sam. Stary `.githooks/` i workflow `commits.yml` zostały usunięte.

2. **Zdalnie — GitHub Ruleset**
   `Settings → Rules → Rulesets → New ruleset → Push` i dodaj regułę
   **Require commit message pattern** z wyrażeniem:

   ```
   ^((feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^()]*\))?(!)?: [^ ].*|Merge branch.*|Merge pull request.*|Merge remote-tracking branch.*|Revert ".*")
   ```

   To ten sam regex co lokalny hook, rozszerzony o commity generowane
   przez gita (`Merge ...`, `Revert "..."`). Nie da się zpushować
   niezgodnego commita bez bypassu rulesetu.

Commity generowane przez gita (`Merge branch ...`, `Revert "..."`) są przepuszczane.
