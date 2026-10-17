# Conventional Commits

Commity używają formatu [Conventional Commits 1.0](https://www.conventionalcommits.org/).
Temat, opcjonalna treść i stopki są po angielsku; dokumentacja projektu jest po polsku.

## Format

```text
<type>[scope][!]: <description>
```

- Typ: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- Zakres jest opcjonalny, np. `core`, `cli`, `tui`, `gui`, `docker`, `tunnel`, `k8s`, `docs`, `repo`.
- `!` przed dwukropkiem oznacza zmianę niezgodną wstecz; opisz ją także stopką `BREAKING CHANGE:`.
- Opis zaczyna się małą literą, jest krótki i nie kończy się kropką.

```text
feat(tui): add table sorting by port
fix(docker): handle IPv6 port mappings
docs(gui): clarify desktop installation
refactor(core)!: change snapshot schema
```

## Hooki lokalne

Po zainstalowaniu Lefthook uruchom w repozytorium:

```bash
lefthook install
```

Konfiguracja znajduje się w [lefthook.yml](../lefthook.yml):

- `commit-msg` uruchamia [walidator formatu](../scripts/check_commit_msg.py).
- `pre-commit` sprawdza lint i formatowanie Pythona przez Ruff.

Walidator sprawdza format, nie język. Rozpoznaje też automatyczne wiadomości
merge i revert. Hooki są lokalne i mogą zostać pominięte przez `--no-verify`;
nie stanowią zdalnego wymuszenia reguł repozytorium.

Pełny zestaw kontroli: [rozwój i testy](development.md).
