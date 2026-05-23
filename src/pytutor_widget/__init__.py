"""
codelens_widget
================

A CodeLens-style execution visualizer for Jupyter that uses **Philip Guo's real
Online Python Tutor frontend** (`pytutor.js`). The trace is produced in the live
kernel by Guo's own ``pg_logger`` (vendored, MIT-licensed), so the data is in his
exact schema; it is then handed to ``pytutor.js`` rendered inside a self-contained
``<iframe>`` so the legacy jQuery/jsPlumb visualizer runs in the clean document it
expects. Everything (pytutor.js, jsPlumb 1.3.10, jQuery, jQuery UI, D3 v2) is
vendored under ``vendor/``, so it works fully offline and identically across
VS Code, JupyterLab, Notebook 7, and Colab.

Usage
-----
    from codelens_widget import CodeLens

    CodeLens('''
    def insertion_sort(a):
        for i in range(1, len(a)):
            key = a[i]
            j = i - 1
            while j >= 0 and a[j] > key:
                a[j + 1] = a[j]
                j -= 1
            a[j + 1] = key
        return a

    data = [5, 2, 9, 1]
    insertion_sort(data)
    ''')

Or, after import, the cell magic visualizes a whole cell::

    %%codelens
    x = [1, 2, 3]
    y = x
    y.append(4)

Attribution
-----------
Online Python Tutor (``pg_logger.py``, ``pg_encoder.py``, ``pytutor.js`` and the
bundled libraries) is Copyright (C) Philip J. Guo, released under the MIT license.
See the headers of the vendored files. This package only wraps and embeds it.
"""

from __future__ import annotations

import json
import os
import re

import anywidget
import traitlets

from . import pg_logger

try:
    from IPython import get_ipython
    from IPython.display import display as _ipy_display
except Exception:  # pragma: no cover
    def get_ipython():
        return None

    def _ipy_display(*a, **k):
        pass


__all__ = ["CodeLens", "trace_code", "register_codelens_magic"]

_VENDOR = os.path.join(os.path.dirname(__file__), "vendor")

# Load order matters: jQuery -> jQuery UI -> D3 -> jsPlumb -> ba-bbq -> qtip -> pytutor.
_JS_FILES = [
    "jquery.min.js",
    "jquery-ui.min.js",
    "d3.v2.min.js",
    "jsplumb.min.js",
    "jquery.ba-bbq.min.js",
    "jquery.qtip.min.js",
    "pytutor.js",
]
_CSS_FILES = ["jquery-ui.min.css", "jquery.qtip.css", "pytutor.css"]


def _read_vendor(name):
    with open(os.path.join(_VENDOR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _html_inline_safe(text):
    r"""Defuse sequences that would prematurely terminate an inlined ``<script>``.

    The vendor bundle is inlined verbatim into an HTML ``<script>`` element, but
    ``pytutor.js`` contains literal ``</script>`` and ``<!--`` -- in its header
    comment (which shows example ``<script src=...>`` includes) and in one string
    that builds a ``<script>`` block. The browser's HTML tokenizer ends the
    element at the first ``</script`` and is knocked into its "escaped" state by
    ``<!--``, so without this everything after pytutor.js's header (including the
    global ``ExecutionVisualizer`` definition) is parsed as stray HTML and never
    runs. Backslash-escaping the ``<`` lead-in hides the tag from the tokenizer
    while staying inert in JS: inside a string ``"<\/script>"`` == ``"</script>"``
    and ``"<\!--"`` == ``"<!--"``, and inside a comment it is just text. (We do
    *not* touch the ``<script`` opening tag -- it is harmless in script-data state
    and also occurs inside minified jQuery/qTip code.) This generalises the guard
    that ``_build_html`` already applies to the embedded trace JSON.
    """
    text = re.sub(r"</(script|style)", lambda m: "<\\/" + m.group(1), text, flags=re.IGNORECASE)
    return text.replace("<!--", "<\\!--")


# Concatenate the vendor bundle once at import (module-level cache).
def _load_bundle():
    js = "\n;\n".join(_read_vendor(n) for n in _JS_FILES)
    css = "\n".join(_read_vendor(n) for n in _CSS_FILES)
    return _html_inline_safe(js), _html_inline_safe(css)


_BUNDLE_JS, _BUNDLE_CSS = _load_bundle()


# --------------------------------------------------------------------------- #
# Trace generation -- Guo's exact schema, via the vendored logger.            #
# --------------------------------------------------------------------------- #

def trace_code(code, cumulative_mode=False, heap_primitives=False,
               allow_all_modules=True):
    """Return ``{"code": <source>, "trace": [...]}`` in Online Python Tutor's
    exact format, produced by Guo's own ``pg_logger``."""

    def finalizer(input_code, output_trace):
        return {"code": input_code, "trace": output_trace}

    return pg_logger.exec_script_str_local(
        code, None, cumulative_mode, heap_primitives, finalizer,
        allow_all_modules=allow_all_modules,
    )


# --------------------------------------------------------------------------- #
# Self-contained HTML document for the iframe.                                #
# --------------------------------------------------------------------------- #

_DEFAULT_OPTIONS = {
    "embeddedMode": True,
    "lang": "py3",
    "disableHeapNesting": False,
    "drawParentPointers": False,
    "textualMemoryLabels": False,
    "showOnlyOutputs": False,
}


def _build_html(trace_data, options):
    trace_json = json.dumps(trace_data)
    # neutralize any "</script>" that might appear inside string data
    trace_json = trace_json.replace("</", "<\\/")
    opts_json = json.dumps(options)

    return """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
""" + _BUNDLE_CSS + """
html, body { margin: 0; padding: 6px; background: #fff;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
#viz { overflow: visible; }
.cl-fail { color: #b00; font: 13px ui-monospace, Menlo, monospace; padding: 8px; }
</style>
</head><body>
<div id="viz"></div>
<script>
""" + _BUNDLE_JS + """
</script>
<script>
(function () {
  var FRAME_ID = "__OPT_FRAME_ID__";
  var traceData = """ + trace_json + """;
  var options = """ + opts_json + """;
  function reportHeight() {
    try {
      var h = document.body.scrollHeight;
      parent.postMessage({ __opt_height: h, __opt_id: FRAME_ID }, "*");
    } catch (e) {}
  }
  function boot() {
    try {
      window.__optViz = new ExecutionVisualizer("viz", traceData, options);
    } catch (e) {
      document.getElementById("viz").innerHTML =
        '<div class="cl-fail">pytutor failed to render: ' + (e && e.message) + '</div>';
    }
    [50, 300, 800].forEach(function (t) { setTimeout(reportHeight, t); });
    window.addEventListener("resize", reportHeight);
  }
  if (window.jQuery) { jQuery(boot); } else { window.addEventListener("load", boot); }
})();
</script>
</body></html>"""


# --------------------------------------------------------------------------- #
# Widget                                                                      #
# --------------------------------------------------------------------------- #

_ESM = r"""
function render({ model, el }){
  el.innerHTML = "";
  const frameId = "opt_" + Math.random().toString(36).slice(2);
  const iframe = document.createElement("iframe");
  iframe.style.width = "100%";
  iframe.style.boxSizing = "border-box";  // count the 1px border inside 100% so the right edge isn't clipped
  iframe.style.display = "block";          // avoid the inline-element descender gap below the frame
  iframe.style.height = (model.get("height") || 520) + "px";
  iframe.style.border = "1px solid #d0d0d8";
  iframe.style.borderRadius = "8px";
  iframe.style.background = "#fff";
  iframe.setAttribute("sandbox", "allow-scripts allow-same-origin");
  iframe.setAttribute("scrolling", "auto");

  const html = (model.get("srcdoc") || "").replace("__OPT_FRAME_ID__", frameId);
  iframe.srcdoc = html;
  el.appendChild(iframe);

  function onMessage(ev){
    const d = ev.data;
    if (d && d.__opt_id === frameId && typeof d.__opt_height === "number"){
      iframe.style.height = Math.max(200, d.__opt_height + 10) + "px";
    }
  }
  window.addEventListener("message", onMessage);

  const onHeight = () => { iframe.style.height = (model.get("height") || 520) + "px"; };
  model.on("change:height", onHeight);

  return () => {
    window.removeEventListener("message", onMessage);
    model.off("change:height", onHeight);
  };
}
export default { render };
"""


class CodeLens(anywidget.AnyWidget):
    _esm = _ESM

    srcdoc = traitlets.Unicode("").tag(sync=True)
    height = traitlets.Int(520).tag(sync=True)

    def __init__(self, code, height=520, lang="py3", options=None,
                 cumulative_mode=False, heap_primitives=False):
        super().__init__()
        if not isinstance(code, str):
            raise TypeError("CodeLens(code) expects a source string")
        self.height = height
        opts = dict(_DEFAULT_OPTIONS)
        opts["lang"] = lang
        opts["heapPrimitives"] = heap_primitives
        if options:
            opts.update(options)
        data = trace_code(code, cumulative_mode=cumulative_mode,
                          heap_primitives=heap_primitives)
        self.srcdoc = _build_html(data, opts)


def register_codelens_magic(ipython=None):
    r"""Register the ``%%codelens`` cell magic.

    In IPython/Jupyter, prefixing a cell with ``%%codelens`` visualizes the cell
    body with :class:`CodeLens` (the cell is traced and rendered, not run the
    usual way). Optional flags on the magic line mirror the constructor::

        %%codelens --height 600 --lang py3
        x = [1, 2, 3]
        y = x
        y.append(4)

    Called automatically on import; returns ``True`` when a live shell is found,
    ``False`` otherwise (e.g. plain Python).
    """
    ip = ipython or get_ipython()
    if ip is None:
        return False

    from IPython.core.magic_arguments import (argument, magic_arguments,
                                              parse_argstring)

    @magic_arguments()
    @argument("--height", type=int, default=520,
              help="iframe height in pixels (default: 520)")
    @argument("--lang", default="py3", choices=("py2", "py3"),
              help="tracer language mode (default: py3)")
    @argument("--cumulative", action="store_true",
              help="accumulate every executed line in the trace")
    @argument("--heap-primitives", action="store_true",
              help="render primitive values as separate heap objects")
    def codelens(line, cell):
        args = parse_argstring(codelens, line)
        if not (cell and cell.strip()):
            print("%%codelens: cell is empty -- put Python code below the magic line.")
            return
        _ipy_display(CodeLens(
            cell, height=args.height, lang=args.lang,
            cumulative_mode=args.cumulative,
            heap_primitives=args.heap_primitives,
        ))

    ip.register_magic_function(codelens, magic_kind="cell", magic_name="codelens")
    return True


try:
    register_codelens_magic()
except Exception:
    pass
