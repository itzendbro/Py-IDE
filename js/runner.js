/* ============================================================
   runner.js — Pyodide (CPython/WASM) lifecycle:
   boot, pip install, run code, lint (pyflakes), complete (jedi)
   Exposes window.Runner
   ============================================================ */
(function () {
  'use strict';

  const PROJECT_DIR = '/home/pyodide/project';
  const PKG_KEY = 'pyide_pip_pkgs_v1';

  let pyodide = null;
  let ready = false;
  let busy = false;
  const extraPackages = new Set(JSON.parse(localStorage.getItem(PKG_KEY) || '[]'));

  // injected by app.js
  let hooks = {
    out: (text, cls) => console.log(text),
    status: (s) => {},
    onReady: () => {},
    guiShow: () => {},
  };

  /* ---------- stdin: input() -> native prompt (synchronous, works in tab) ---------- */
  let stdinBuf = '';
  function stdinHandler() {
    if (stdinBuf.length === 0) {
      const val = window.prompt('Program is waiting for input() — type a value:');
      if (val === null) return null; // EOF
      stdinBuf = val + '\n';
    }
    const code = stdinBuf.charCodeAt(0);
    stdinBuf = stdinBuf.slice(1);
    return code;
  }

  /* ---------- images produced by matplotlib are pushed here ---------- */
  window.showImage = function (dataUrl) {
    const desk = document.getElementById('tk-desktop');
    const hint = document.getElementById('guiHint');
    if (hint) hint.style.display = 'none';
    const wrap = document.createElement('div');
    wrap.className = 'c-img';
    wrap.style.padding = '12px';
    const img = document.createElement('img');
    img.src = dataUrl;
    wrap.appendChild(img);
    desk.appendChild(wrap);
    hooks.guiShow();
  };

  /* ---------- Python setup (defines ide_lint / ide_complete / ide_run) ---------- */
  const SETUP_PY = `
import sys, os, io, json, traceback, builtins, importlib.util

import js

PROJECT = "/home/pyodide/project"
os.makedirs(PROJECT, exist_ok=True)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

def _spec_exists(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

def ide_lint(code, filename):
    """Return JSON list: [severity, lineno(1-based), col(0-based), message]"""
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except Exception:
        return json.dumps([])
    class Col(Reporter):
        def __init__(self):
            super().__init__(io.StringIO(), io.StringIO())
            self.msgs = []
        def unexpectedError(self, fn, mt, exc):
            self.msgs.append(["error", 1, 0, "Linter error: %s" % (exc,)])
        def syntaxError(self, fn, msg, lineno, offset, text):
            self.msgs.append(["error", max(1, lineno or 1), max(0, (offset or 1) - 1), str(msg or "Syntax error")])
        def flake(self, m):
            n = type(m).__name__
            sev = "warning"
            if ("Undefined" in n or "Duplicate" in n or
                n in ("ReturnOutsideFunction", "BreakOutsideLoop", "ContinueOutsideLoop",
                      "LateFutureImport", "ImportStarNotPermitted", "FStringError",
                      "StringDotFormatExtraPositionalArguments", "StringDotFormatExtraNamedArguments")):
                sev = "error"
            col = getattr(m, "col", None)
            if col is None:
                col = getattr(m, "col_offset", None)
            if col is None:
                col = 0
            try:
                txt = m.message % m.message_args if m.message_args else m.message
            except Exception:
                txt = m.message
            self.msgs.append([sev, getattr(m, "lineno", 1) or 1, int(col), str(txt)])
    r = Col()
    try:
        check(code, filename, r)
    except Exception as e:
        r.msgs.append(["error", 1, 0, "Syntax error: %s" % (e,)])
    return json.dumps(r.msgs)


def ide_complete(code, path, line, col):
    """Return JSON list: [label, type, detail, doc]"""
    try:
        import jedi
        try:
            project = jedi.Project(PROJECT)
        except Exception:
            project = None
        try:
            script = jedi.Script(code=code, path=path, project=project, sys_path=list(sys.path))
        except TypeError:
            try:
                script = jedi.Script(code=code, path=path, project=project)
            except TypeError:
                script = jedi.Script(code, path)
        try:
            comps = script.complete(line=line, column=col)
        except Exception:
            comps = []
        out = []
        for c in comps:
            try:
                name = c.name
                if not name:
                    continue
                try:
                    doc = c.docstring(raw=True) or ""
                except Exception:
                    doc = ""
                out.append([name, str(c.type or "text"), (c.description or name)[:300], doc[:500]])
            except Exception:
                continue
        return json.dumps(out)
    except Exception:
        return json.dumps("[]") if False else json.dumps([])


def ide_find_imports(code):
    try:
        from pyodide.code import find_imports
        return json.dumps(find_imports(code))
    except Exception:
        return json.dumps([])


async def _install(pkg, quiet=False):
    import micropip
    if not quiet:
        print("\\xf0\\x9f\\x93\\xa6 Installing %s ... (first time takes a bit)" % pkg, flush=True)
    try:
        await micropip.install(pkg, keep_going=True)
        if not quiet:
            print("\\xe2\\x9c\\x85 Installed %s" % pkg, flush=True)
        return True
    except Exception as e:
        print("\\xe2\\x9a\\xa0\\xef\\xb8\\x8f Could not install %s: %s" % (pkg, e), flush=True)
        return False


async def ide_run(path):
    os.chdir(PROJECT)
    try:
        src = open(path, encoding="utf-8").read()
    except Exception:
        src = ""

    # auto-install missing third-party imports
    try:
        from pyodide.code import find_imports
        mods = find_imports(src)
    except Exception:
        mods = []
    mapping = {
        "PIL": "pillow", "sklearn": "scikit-learn", "yaml": "pyyaml",
        "bs4": "beautifulsoup4", "OpenSSL": "pyopenssl", "cv2": "opencv-python",
        "dateutil": "python-dateutil", "serial": "pyserial", "dotenv": "python-dotenv",
        "fitz": "pymupdf", "skimage": "scikit-image",
    }
    for m in mods:
        top = m.split(".")[0]
        if top in ("tkinter", "tkinter.ttk", "matplotlib"):
            continue
        if top in sys.builtin_module_names or _spec_exists(top):
            continue
        pkg = mapping.get(top, top)
        await _install(pkg)

    # reset GUI (close old tk windows from the previous run)
    try:
        import sys as _sys
        _tk_mod = _sys.modules.get("tkinter")
        if _tk_mod is not None and hasattr(_tk_mod, "_reset"):
            _tk_mod._reset()
    except Exception:
        pass

    ns = {"__name__": "__main__", "__file__": path}
    try:
        exec(compile(src, path, "exec"), ns)
    except SystemExit:
        pass
    except BaseException:
        traceback.print_exc()

    # render matplotlib figures to the GUI panel
    try:
        import matplotlib
        matplotlib.use("agg")
        import matplotlib.pyplot as plt
        import base64
        for num in plt.get_fignums():
            fig = plt.figure(num)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
            js.globalThis.showImage("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
        plt.close("all")
    except Exception:
        pass

    print("\\n\\xe2\\x9c\\x85 Program finished.")
`;

  /* ---------- sync virtual FS into Pyodide's MEMFS ---------- */
  function syncFS() {
    const FS = pyodide.FS;
    function ensureDir(path) {
      try { FS.mkdir(path); } catch (e) { /* exists */ }
    }
    ensureDir(PROJECT_DIR);
    const files = window.Files.allFiles();
    for (const f of files) {
      const rel = window.Files.pathOf(f);
      const parts = rel.split('/');
      let dir = PROJECT_DIR;
      for (let i = 0; i < parts.length - 1; i++) {
        dir += '/' + parts[i];
        ensureDir(dir);
      }
      try {
        FS.writeFile(PROJECT_DIR + '/' + rel, f.content || '');
      } catch (e) {
        console.warn('write failed', rel, e);
      }
    }
  }

  /* ---------- boot ---------- */
  async function boot() {
    if (pyodide) return;
    try {
      hooks.status('Loading Python runtime (WASM)…');
      pyodide = await window.loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.29.4/full/',
      });

      pyodide.setStdout({ batched: (s) => hooks.out(String(s), 'out') });
      pyodide.setStderr({ batched: (s) => hooks.out(String(s), 'err') });
      pyodide.setStdin({ stdin: stdinHandler });

      hooks.status('Loading micropip…');
      await pyodide.loadPackage(['micropip']);

      hooks.status('Installing autocomplete + error-lens engine (jedi, pyflakes)…');
      await pyodide.runPythonAsync(
        `import micropip; await micropip.install(["jedi", "pyflakes"], keep_going=True)`
      );

      // restore user packages
      for (const p of extraPackages) {
        hooks.status('Restoring package: ' + p);
        try {
          await pyodide.runPythonAsync(
            `import micropip; await micropip.install(${JSON.stringify(p)}, keep_going=True)`
          );
        } catch (e) { /* will retry on demand */ }
      }

      // tkinter browser shim
      hooks.status('Setting up Tkinter support…');
      const shim = await fetch('py/tkinter_shim.py').then((r) => r.text());
      await pyodide.runPythonAsync(shim);

      await pyodide.runPythonAsync(SETUP_PY);

      syncFS();
      ready = true;
      hooks.onReady();
      hooks.status('Python ready');
      hooks.out('Python 3.12 (Pyodide/WASM) is ready. Autocomplete (Jedi) and Error Lens (pyflakes) are active.\n' +
        'Type code and press Run — pip install works, and Tkinter windows show in the GUI Preview tab.\n', 'sys');
    } catch (e) {
      hooks.status('Python failed to start');
      hooks.out('Failed to start Python runtime: ' + (e && e.message ? e.message : e) +
        '\nCheck your internet connection (Pyodide loads from a CDN) and reload.', 'err');
    }
  }

  /* ---------- run current file ---------- */
  async function run(node) {
    if (!ready) { hooks.out('Python is still starting, please wait…', 'sys'); return; }
    if (busy) { hooks.out('A program is already running. (Infinite loop? Reload the page to reset.)', 'sys'); return; }
    busy = true;
    try {
      syncFS();
      const rel = window.Files.pathOf(node);
      const path = PROJECT_DIR + '/' + rel;
      const fname = rel.split('/').pop();
      // clear old matplotlib images
      document.querySelectorAll('#tk-desktop .c-img').forEach((el) => el.remove());
      const hint = document.getElementById('guiHint');
      if (hint) hint.style.display = '';

      hooks.out('▶ Running ' + fname + ' …', 'sys');
      await pyodide.runPythonAsync('await ide_run(' + JSON.stringify(path) + ')');
    } catch (e) {
      const msg = String(e && e.message ? e.message : e);
      hooks.out(msg, 'err');
    } finally {
      busy = false;
    }
  }

  /* ---------- lint ---------- */
  async function lint(code, path) {
    if (!ready || busy) return [];
    try {
      pyodide.globals.set('__lint_code', code);
      pyodide.globals.set('__lint_path', path);
      const raw = await pyodide.runPythonAsync('ide_lint(__lint_code, __lint_path)');
      const arr = JSON.parse(String(raw));
      return arr;
    } catch (e) {
      return [];
    }
  }

  /* ---------- autocomplete ---------- */
  async function complete(code, path, line, col) {
    if (!ready || busy) return [];
    try {
      pyodide.globals.set('__cc', code);
      pyodide.globals.set('__cp', path);
      pyodide.globals.set('__cl', line);
      pyodide.globals.set('__ck', col);
      const raw = await pyodide.runPythonAsync('ide_complete(__cc, __cp, __cl, __ck)');
      return JSON.parse(String(raw));
    } catch (e) {
      return [];
    }
  }

  /* ---------- pip package management ---------- */
  async function installPackage(name) {
    if (!ready) throw new Error('Python still starting');
    name = String(name || '').trim();
    if (!name) return false;
    const ok = await pyodide.runPythonAsync(
      `await _install(${JSON.stringify(name)})`
    );
    if (ok) {
      extraPackages.add(name);
      localStorage.setItem(PKG_KEY, JSON.stringify([...extraPackages]));
    }
    return !!ok;
  }

  function packages() { return [...extraPackages]; }
  function isReady() { return ready; }
  function isBusy() { return busy; }

  window.Runner = {
    boot, run, lint, complete, installPackage, packages,
    isReady, isBusy, syncFS,
    setHooks(h) { hooks = Object.assign(hooks, h); },
  };
})();
