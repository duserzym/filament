# Calculation walkthrough site

The walkthrough website lives in `docs/site/` and is configured by `mkdocs.yml` at the repository root. Only
`docs/site/` is built; the other notes in `docs/` (parity reports, research notes, specifications) stay internal.
The site is not published. Publishing waits for Yiming's decision (options below).

## Build and preview

```sh
/opt/homebrew/bin/python3.14 -m venv .venv-docs
.venv-docs/bin/pip install mkdocs==1.6.1 mkdocs-material==9.8.1 mkdocs-macros-plugin==1.5.0 pymdown-extensions==13.1
NO_MKDOCS_2_WARNING=1 .venv-docs/bin/mkdocs build --strict      # static site in build/site
.venv-docs/bin/python -m http.server 8771 --bind 127.0.0.1 --directory build/site
```

`build/site/index.html` also opens directly from disk (`use_directory_urls: false`, and the plot data is a script,
not a fetched JSON file). MathJax and Plotly load from pinned jsDelivr URLs, so equations and plots need a network.

## Numbers on the pages

Pages never contain hand-typed numbers. `{{ v.… }}` macros read `docs/site/data/values.json`; the interactive
dead-time page reads `docs/site/javascripts/z1-data.js`. Both are written by

```sh
env -u PYTHONPATH .venv/bin/python scripts/docs_site_data.py
```

which reads the example acquisitions read-only, runs filament's own reduction, and runs IDTIMS_UPbRPy (its own
venv, one subprocess) for the dates at every slider position from 25.0 to 50.0 ns in 0.1 ns steps. The output is
byte-identical on rerun. `tests/test_docs_site.py` checks that every page reference resolves, that no source
metadata (sample names, file names, paths, calendar dates) reaches the public files, that the browser maths in
`deadtime.js` reproduces the engine's ratio means and %SE (Node), and, when the example data and the age-engine
venv are available (slow tier), that a fresh run of the generator equals the committed files.

Re-run the generator and the test after any change to the reduction engine, the age engine or the saved project.

## Publishing options (not done)

- **GitHub Pages from this repository.** The repository is private. Pages from a private repository needs a paid
  GitHub plan, and even then the site itself is public on the internet; only GitHub Enterprise Cloud can restrict
  Pages to signed-in members. Same workflow pattern as UPbRPy (`docs-pages.yml`, manual dispatch).
- **A separate public docs repository** (for example `duserzym/filament-docs`) that receives only the built site
  or only `docs/site/` + `mkdocs.yml`. Free Pages, keeps the code private, but the site is public.
- **Lab-only hosting** on the lab desktop over Tailscale (like UPbDB): private to the tailnet, no GitHub change.
- **Private shared page** (a Claude artifact or a zip of `build/site`): private by default, shareable by link or file.
- **Make filament public** and use its own Pages. A larger decision about the code itself.
