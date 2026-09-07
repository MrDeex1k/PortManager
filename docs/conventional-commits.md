# Conventional Commits

Wszystkie commity **muszą** spełniać [Conventional Commits 1.0](https://www.conventionalcommits.org/).

**Wiadomości commitów muszą być po angielsku** — zarówno temat, jak i opcjonalna
treść oraz stopki. Dokumentacja projektu pozostaje po polsku.

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
feat(tui): add table sorting by port
fix(docker): fix IPv6 port mapping parsing
docs: document the decision to develop without Docker
refactor(core)!: make PortEntry a frozen dataclass
chore(repo): add conventional commits hook
```

Breaking change opisuj też w stopce (`BREAKING CHANGE: ...`), ale samo `!` wystarcza do zaliczenia hooka.

## Egzekwowanie

> Stan na 2026-09-06 (zweryfikowane w docsach GitHuba): reguła
> `Commit message pattern` istnieje tylko w dokumentacji
> GitHub Enterprise Cloud — na darmowym planie (nawet przy publicznym
> repo) nie ma ani jej, ani push rulesetu z takim wzorcem
> (push rulesety na Free kryją tylko: ścieżki, rozszerzenia i rozmiary plików).
> Dlatego zdalne egzekwowanie formatu bez Actions jest u nas niewykonalne.

1. **Lokalnie — lefthook** (model zaufania).
   Hook `commit-msg` z `lefthook.yml` wywołuje `scripts/check_commit_msg.py`
   (czysty stdlib, ten sam regex co wcześniej, działa na Win/Mac/Linux).
   Hook sprawdza format, nie język — wymóg angielskiego obowiązuje autora commita.

   Po klonie repo wykonaj raz:

   ```bash
   # najpierw sam lefthook (jedno z):
   brew install lefthook                # macOS
   winget install evilmartians.lefthook  # Windows
   uv tool install lefthook              # dowolny OS

   # potem podpięcie hooków w tym repo:
   lefthook install
   ```

   Zły format = commit odrzucony z podpowiedzią. Ograniczenie:
   `git commit --no-verify` omija hooka — nie ma zdalnej siatki bez
   Actions ani płatnego planu, więc format trzymamy dyscypliną + review PR.
   Nie ustawiaj ręcznie `git config core.hooksPath` — lefthook zarządza
   `.git/hooks` sam. Stary `.githooks/` i workflow `commits.yml` zostały usunięte.

2. **Zdalnie — branch ruleset (ochrona historii, nie formatu).**
   `Settings → Rules → New ruleset → New branch ruleset`, target `main`:
   `Restrict deletions` + `Block force pushes`. To nie sprawdza treści
   commitów, ale chroni wyczyszczoną historię. Opcje `Require a pull request`
   / `Require status checks` / `Require signed commits` zostawiamy wyłączone
   (solowy dev, brak CI, brak podpisywania).

Commity generowane przez gita (`Merge branch ...`, `Revert "..."`) są przepuszczane.
