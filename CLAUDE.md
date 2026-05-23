# CLAUDE.md

Project context for `pytutor_widget` — a CodeLens / Python-Tutor execution
visualizer for Jupyter that emits **Philip Guo's exact trace schema** and renders
it with his **real `pytutor.js`** frontend, embedded in a self-contained iframe.

## What this is (and how it differs from the sibling)

There are two execution-visualizer approaches in this lineage:

- `codelens_widget.py` (sibling): a *custom* dependency-free tracer + hand-rolled
  stepper. Light, offline, but a from-scratch renderer.
- `pytutor_widget/` (this package, under `src/`): emits **Guo's exact `{code, trace}` schema**
  via his vendored `pg_logger`, and renders with the **real Online Python Tutor
  frontend**. You inherit OPT's battle-tested reference diagrams (jsPlumb arrows,
  nested heap layout) at the cost of bundling its legacy JS stack.

Use this one when you want fidelity to Python Tutor; use the sibling when you want
a minimal, fully self-authored renderer.

## Project layout

```
src/pytutor_widget/
  __init__.py        # trace_code(), _build_html(), CodeLens widget, %%codelens magic
  pg_logger.py       # VENDORED (patched) -- Guo's bdb-based tracer; entry: exec_script_str_local
  pg_encoder.py      # VENDORED (unmodified) -- value/heap encoder (REF, LIST, DICT, INSTANCE, ...)
  NOTICE             # MIT attribution for Online Python Tutor
  vendor/            # VENDORED frontend + its pinned dependencies (see below)
docs/pages/overview.ipynb   # showcase + headless schema self-test
pyproject.toml       # packaging; runtime deps: anywidget, traitlets; ships vendor/* + NOTICE
CLAUDE.md
```

## Environment & commands

- Python 3.9+ (works on 3.12+ after the `imp` patch below). Runtime deps (`anywidget`,
  `traitlets`) are declared in `pyproject.toml`; install the package with `pip install -e .`.
- After install: `from pytutor_widget import CodeLens` (the importable package lives at `src/pytutor_widget/`).
- Headless schema test (no browser needed): run the notebook's final cell.
- JS sanity check of our own glue (not the vendored libs):
  ```bash
  python -c "import pytutor_widget as c; open('/tmp/e.mjs','w').write(c._ESM)"
  node --check /tmp/e.mjs
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
`pytutor.js`. CSS: `jquery-ui.min.css`, `jquery.qtip.css`, `pytutor.css`.

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
jsPlumb at 1.3.10 and D3 at v2. Re-run the notebook's schema self-test and `node --check`.

## Testing approach

- **Schema (headless, authoritative):** `trace_code` output is deterministic and fully
  validatable -- assert the per-point keys, `REF` aliasing (two names -> identical
  `["REF",id]`), heap tags (`LIST`/`INSTANCE`/...), `stack_to_render` depth on recursion,
  and `json.dumps` round-trip. This is the contract with `pytutor.js`.
- **Glue (headless):** `node --check` on `_ESM` and on the inner boot `<script>`.
- **Visual (manual):** open `docs/pages/overview.ipynb` in the target notebook frontend.
