# Third-party skills

Copied on 2026-11-08 from the repos below. Each folder keeps its upstream license file. To
update one, re-copy the folder from the repo and re-apply the change listed for it.

| Skill | Source (commit) | License | Local change |
|---|---|---|---|
| `webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills) `skills/webapp-testing` (2c5958ecac7c) | Apache-2.0 (`LICENSE.txt`) | none |
| `graphql-operations` | [apollographql/skills](https://github.com/apollographql/skills) `skills/graphql-operations` (9dda13977303) | MIT, Apollo Graph, Inc. | removed `allowed-tools: Bash(npm:*) Bash(npx:*) ...` |
| `systematic-debugging` | [obra/superpowers](https://github.com/obra/superpowers) `skills/systematic-debugging` (22f0b463e7a5) | MIT, Jesse Vincent | `superpowers:` skill names unprefixed; the TDD pointer replaced with this project's equivalent (it has no test suite) |
| `verification-before-completion` | same repo (22f0b463e7a5) | MIT, Jesse Vincent | none |
| `dart-run-static-analysis` | [dart-lang/skills](https://github.com/dart-lang/skills) `skills/dart-run-static-analysis` (fa691671fda3; identical copy in flutter/agent-plugins) | BSD-3-Clause, the Dart project authors | none. For Tsumiru (upstream code) run `dart analyze` as configured; do not tighten its `analysis_options.yaml` |
| `dart-resolve-package-conflicts` | same repo (fa691671fda3) | BSD-3-Clause | none. Tsumiru's `pubspec.lock` is upstream's: resolve, do not upgrade |
| `ruff` | [astral-sh/claude-code-plugins](https://github.com/astral-sh/claude-code-plugins) `plugins/astral/skills/ruff` (855418fb9ebf) | MIT or Apache-2.0 (both files kept) | none. There is no uv here: ruff is `readahead/.venv/bin/ruff` |

Also left out: `dart-fix-runtime-errors` and `flutter-fix-layout-issues` (flutter/agent-plugins)
work through a Dart/Flutter MCP server with hot reload, which this setup does not run; Astral's
`uv` (readahead uses venv + pip) and `ty`.

Considered and left out: Vercel's `react-best-practices` (mostly Next.js and server rules),
softaworks `mui` (written for MUI v7, invents a `useMuiSnackbar` hook; this repo is on v9),
softaworks `react-dev` (Server Components focus).

Removed with the WebUI (2026-11-09): `apollo-client` and `react-useeffect` (in git history).

Upstream advice is written for new apps. Here Tsumiru is someone else's code carried as small
patches, so its existing conventions win (see `ui-patch`).
