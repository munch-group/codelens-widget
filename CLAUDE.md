# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Project context for `codelens_widget` — a CodeLens / Python-Tutor execution
visualizer for Jupyter that emits **Philip Guo's exact trace schema** and renders
it with his **real `pytutor.js`** frontend, embedded in a self-contained iframe.

## History note: a since-fixed import bug

At one point `_JS_FILES`/`_CSS_FILES` in `src/codelens_widget/__init__.py` (plus
the module docstring and `NOTICE`) referenced `codelens.js`/`codelens.css`, while
the actual vendored files in `vendor/` were still named `pytutor.js`/`pytutor.css`
— an incomplete rename pass that updated references but never renamed (or
re-vendored) the physical assets, so `import codelens_widget` crashed with
`FileNotFoundError`. Fixed by restoring the `pytutor.js`/`pytutor.css` names
throughout (the vendor files are correctly named — Guo's frontend is genuinely
called `pytutor.js`; don't rename the assets to match a future stray reference
without checking `vendor/` first).

There was also an orphaned duplicate package, `src/pytutor_widget/` — a leftover
copy of `codelens_widget` from before that rename, unreferenced anywhere but
auto-discovered and shipped as a second top-level package by
`[tool.setuptools.packages.find]` (which only excludes `test*`). It has been
removed; if something like it reappears, check
`python -c "from setuptools import find_packages; print(find_packages(where='src', exclude=['test*']))"`
to confirm only `codelens_widget` is packaged.

## What this is (and how it differs from the sibling)

There are two execution-visualizer approaches in this lineage:

- `codelens_widget.py` (sibling, separate repo): a *custom* dependency-free tracer + hand-rolled
  stepper. Light, offline, but a from-scratch renderer.
- `codelens_widget/` (this package, under `src/`): emits **Guo's exact `{code, trace}` schema**
  via his vendored `pg_logger`, and renders with the **real Online Python Tutor
  frontend**. You inherit OPT's battle-tested reference diagrams (jsPlumb arrows,
  nested heap layout) at the cost of bundling its legacy JS stack.

Use this one when you want fidelity to Python Tutor; use the sibling when you want
a minimal, fully self-authored renderer.

## Project layout

```
src/codelens_widget/
  __init__.py        # trace_code(), _build_html(), CodeLens widget, %%codelens magic
  pg_logger.py        # VENDORED (patched) -- Guo's bdb-based tracer; entry: exec_script_str_local
  pg_encoder.py       # VENDORED (unmodified) -- value/heap encoder (REF, LIST, DICT, INSTANCE, ...)
  NOTICE               # MIT attribution for Online Python Tutor
  vendor/              # VENDORED frontend + its pinned dependencies (see below)
src/pytutor_widget/    # orphaned duplicate of codelens_widget -- see "Known broken state" above
docs/pages/overview.ipynb  # doc-site landing page: install instructions + one live %%codelens example
docs/pages/demo.ipynb      # showcase notebook: aliasing, nested structures, recursion, classes, and
                            # the headless schema self-test (final two cells, "8. Self-test")
docs/api/                  # quartodoc-generated API reference (built via `pixi run api`)
review-kit/                 # standalone /review, /review-apply, /review-init Claude Code workflow
  (installed into .claude/agents/ and .claude/commands/; see review-kit/README.md)
scripts/                    # bump_version.py, bump_changelog.py, git-commit.sh, github-release.sh,
                            # docs-build-render.sh, docs-run-notebooks.sh, rename.py (template-fork init)
pyproject.toml        # packaging; runtime deps: anywidget, traitlets; ships vendor/* + NOTICE; pixi tasks
CLAUDE.md
```

## Environment & commands

This project uses **pixi**, not a bare pip/venv workflow. All commands below are
`pixi run <task>` (defined in `[tool.pixi.tasks.*]` in `pyproject.toml`).

- `pixi run install-dev` — editable install (`pip install --no-build-isolation --force-reinstall --no-deps -e .`).
- `pixi run test` — runs `pytest tests/pytest/`, after first `nbconvert`-ing
  `docs/pages/tutorial/*.ipynb` into that directory as scripts. **Note:** no
  `docs/pages/tutorial/` directory and no `tests/pytest/` suite currently exist in
  this repo, so this task is presently a no-op template stub, not a real test gate.
  The one thing that *is* an authoritative, runnable check is the headless schema
  self-test at the end of `docs/pages/demo.ipynb` (see below) — there is no `pytest`
  suite to point to instead.
- `pixi run api` — builds the quartodoc API reference (`./scripts/docs-build-render.sh`).
- `pixi run docs` — executes the documentation notebooks in place (`./scripts/docs-run-notebooks.sh`).
- `pixi run bump` / `pixi run release` / `pixi run version` — version bump (`scripts/bump_version.py
  --patch|--minor|--major`), commit, and (for `release`/`version`) push + `scripts/github-release.sh`
  to trigger the conda/PyPI build. `version` additionally depends on `test`, `api`, `docs`, `commit`
  running clean first. The conda build (`conda-build/meta.yaml`, run by
  `.github/workflows/conda-release.yml` on tag push) pins its `python` host/run
  requirement to `pyproject.toml`'s `requires-python` via Jinja
  (`load_file_data("../pyproject.toml", ...)`) — keep it that way rather than
  hardcoding a version, since an unconstrained `python` requirement lets
  conda-build's solver pick whatever the current conda-forge default Python is
  (this broke the build once already when the default moved past the
  `requires-python` upper bound).
- `pixi run commit` — `./scripts/git-commit.sh` (repo's own commit helper).
- `pixi run clean` — `git clean -id` (interactive, respects `.gitignore`).
- No lint/format/type-check tooling (ruff, black, mypy, etc.) is configured in this repo.

Headless verification without pixi:
```bash
python -c "
from codelens_widget import trace_code
t = trace_code('x = [1, 2, 3]\ny = x\ny.append(4)')
print(t['trace'][-1])
"
```
JS sanity check of *our own* glue code (not the vendored libs):
```bash
python -c "import codelens_widget as c; open('/tmp/e.mjs','w').write(c._ESM)"
node --check /tmp/e.mjs
```

Docs site (Quarto + quartodoc), per `docs/README.md`:
```bash
pip install .
python -m quartodoc build       # builds API reference + objects.json inventory
python -m quartodoc interlinks  # retrieves inventory files for external doc sources
quarto preview                  # live preview
```

## Architecture / data flow

1. `trace_code(src)` calls `pg_logger.exec_script_str_local(src, None, cumulative,
   heap_primitives, finalizer, allow_all_modules=True)` with a finalizer that returns
   `{"code": src, "trace": [...]}`. **The code runs in the live kernel** (we are not a
   sandboxed web service like pythontutor.com), which is why tracing in-process is fine.
2. `_build_html(trace, options)` assembles a **complete HTML document**: the vendored
   CSS inline in `<style>`, the vendored JS inline in `<script>` (in the load order in
   `_JS_FILES`), then a boot script that does
   `new ExecutionVisualizer("viz", traceData, options)` and posts its height to the parent.
3. The `CodeLens` widget syncs that document as the `srcdoc` traitlet. The `_ESM` frontend
   creates an `<iframe>`, sets `srcdoc`, and listens for the height `postMessage` to
   auto-resize.
4. `register_codelens_magic()` runs at import time (wrapped in a bare `try/except` so
   plain-Python imports don't fail outside IPython) and registers the `%%codelens` cell
   magic, which traces the cell body and displays a `CodeLens` instead of executing it
   the normal way.

### Why an iframe (important)

`pytutor.js` is a legacy jQuery + jsPlumb app that expects to own a normal `document`
(global jQuery, absolute-positioned SVG connectors, jQuery-UI slider). Embedding it
directly into the notebook output DOM invites CSS collisions, global clashes, and
jsPlumb offset bugs. A `srcdoc` iframe gives it the clean document it was written for, so
it renders the same in VS Code, JupyterLab, and Colab. The trace is **precomputed in the
kernel**, so the iframe only ever renders *data* -- it never executes user code -- which is
why `sandbox="allow-scripts allow-same-origin"` is safe here.

## Guo's schema (what `pytutor.js` consumes)

Top level: `{"code": <source str>, "trace": [ <point>, ... ]}`. Each point has:
`line`, `event` (`step_line`/`call`/`return`/`exception`/`uncaught_exception`/
`instruction_limit_reached`), `func_name`, `globals` (name->encoded), `ordered_globals`,
`stack_to_render` (frames with `func_name`, `encoded_locals`, `ordered_varnames`,
`is_highlighted`, `frame_id`, `unique_hash`, ...), `heap`, `stdout`.

Value encoding (`pg_encoder`): primitives inline (numbers/str/bool/None; special floats
as `["SPECIAL_FLOAT","NaN"]`); compound values as `["REF", id]` with the object stored once
in `heap` keyed by that id. Heap objects are tagged lists: `["LIST", ...]`, `["TUPLE", ...]`,
`["DICT", [k,v], ...]`, `["SET", ...]`, `["INSTANCE", "Cls", [attr,val], ...]`,
`["FUNCTION", "name(args)", parent_frame_id]`, `["CLASS", ...]`. Aliasing/cycles fall out of
the REF model for free (two names -> same id -> one box, two arrows).

**Heap key gotcha:** in the Python dict, `heap` keys are *ints*; after `json.dumps` they
become *strings* (JSON requires string keys). `pytutor.js` expects the string-keyed JSON
form, so always validate post-serialization, not the in-memory dict.

## Vendored assets & pinned versions (in `vendor/`, load order in `_JS_FILES`)

`jquery.min.js` (1.8.2) -> `jquery-ui.min.js` (1.11.4) -> `d3.v2.min.js` (D3 **v2**) ->
`jsplumb.min.js` (**jsPlumb 1.3.10**) -> `jquery.ba-bbq.min.js` -> `jquery.qtip.min.js` ->
`pytutor.js`. CSS: `jquery-ui.min.css`, `jquery.qtip.css`, `pytutor.css`. Total bundle
is ~850 KB, inlined verbatim into every `CodeLens` instance's `srcdoc`.

**Do not upgrade jsPlumb past 1.3.10** -- pytutor.js uses its old connector API and breaks
on newer versions (per Guo's own header comment). D3 must stay v2 for the same reason.

## Patches applied to the vendored backend (re-apply if you re-vendor)

- `pg_logger.py`: `import imp` -> an `importlib`-based shim (the `imp` module was removed in
  Python 3.12; `imp.new_module` is replaced by `types.ModuleType`).
- `pg_logger.py`: `import pg_encoder` -> `from . import pg_encoder` (so it works as a subpackage).
- `pg_logger.py`: `DEBUG = True` -> `DEBUG = False` (otherwise erroring user code prints a
  bdb traceback to the cell's stderr; with DEBUG off the error is captured as an
  `exception` trace point instead, which is what we want).
- `pg_logger.py`: two regex literals made raw (`r'class\s+'`, `r'\Z(?ms)'`) to silence
  `SyntaxWarning` on modern Python.
- The `resource`/`setrlimit` sandbox is Unix-only but already guarded by `try/except` and
  by `disable_security_checks` (which `exec_script_str_local` sets), so no patch needed.
- `pg_encoder.py` is unmodified.

## Gotchas & constraints

- The HTML document inlines the full ~850 KB vendor bundle, so each `CodeLens` instance
  ships ~850 KB in its `srcdoc` traitlet. Fine on local kernels and Colab; just don't put
  hundreds of them in one notebook.
- **Core-Python only**, like Runestone's directive: only execution *state* is visualized.
  Side effects beyond stdout (turtle, matplotlib, file/network I/O) are not shown.
- `allow_all_modules=True` is passed because the code runs in the user's own kernel; drop
  it if you ever expose this to untrusted input (and re-enable the security checks).
- Constructor options live in `_DEFAULT_OPTIONS` and are overridable via
  `CodeLens(code, options={...})`; `embeddedMode=True` gives the compact inline layout.
- Browser support: the iframe + `postMessage` auto-resize works in Chromium (VS Code,
  Colab) and modern Firefox/Safari. The visual rendering is the one thing not covered by
  the headless tests -- verify once in your target frontend.

## Updating the vendored Online Python Tutor

Re-fetch `pg_encoder.py`, `pg_logger.py`, and the `v3/js` + `v3/css` assets from an OPT
source, drop them into place, then re-apply the four `pg_logger.py` patches above. Keep
jsPlumb at 1.3.10 and D3 at v2. Re-run the schema self-test in `docs/pages/demo.ipynb`
and `node --check`.

## Testing approach

- **Schema (headless, authoritative):** `trace_code` output is deterministic and fully
  validatable -- assert the per-point keys, `REF` aliasing (two names -> identical
  `["REF",id]`), heap tags (`LIST`/`INSTANCE`/...), `stack_to_render` depth on recursion,
  and `json.dumps` round-trip. This is the contract with `pytutor.js`. The reference
  implementation of this check is the final "Self-test" section of
  `docs/pages/demo.ipynb` -- there is no separate `pytest` suite (see the `pixi run test`
  note above).
- **Glue (headless):** `node --check` on `_ESM` and on the inner boot `<script>`.
- **Visual (manual):** open `docs/pages/demo.ipynb` (or `docs/pages/overview.ipynb`) in
  the target notebook frontend.
