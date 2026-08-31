# Py-IDE — Online Python IDE (HTML / CSS / JS only)

A mobile-friendly Python IDE that runs entirely in the browser. No backend, no
build step — open `index.html` (or serve the folder with any static server).

## Features

- 🐍 **Run Python in the browser** via [Pyodide](https://pyodide.org) (CPython compiled to WebAssembly)
- 💡 **Autocomplete & suggestions** powered by [Jedi](https://jedi.readthedocs.io) (same engine behind many IDEs)
- 🩺 **Error Lens like VS Code**: inline error messages, squiggles and gutter markers (pyflakes)
- 📦 **pip install**: a Pip button + automatic install of missing imports (via micropip; pure-Python wheels work)
- 🪟 **Tkinter support**: GUI programs (`tkinter` / `ttk`, Canvas, buttons, inputs, Notebook, Treeview…)
  render as real, draggable windows in the **GUI Preview** tab. `matplotlib` charts show there too.
- 📁 **File explorer**: create / delete / rename files and folders, with colored file-type icons
  (Python, JSON, JS, HTML, CSS, Markdown, images, archives…)
- ⬆ **Import** files or a whole folder (preserves folder structure)
- ⬇ **Export** the whole project as a `.zip`, or the current file
- 📱 **Mobile-first layout**: slide-out explorer, big tap targets, on-screen keyboard friendly
- 🧠 Editor: code folding, bracket matching, search (Ctrl/Cmd+F), multi-cursor, undo/redo,
  syntax highlighting for many languages
- 💾 All files are saved automatically in your browser (localStorage)

## Running it

Any static file server works:

```bash
cd Py-IDE
python3 -m http.server 8080
# open http://localhost:8080
```

Or just open `index.html` directly in a browser.
An internet connection is needed the first time so Pyodide and the editor
components can load from CDNs; afterwards much of it is cached.

## Project layout

| File | Purpose |
|---|---|
| `index.html` | App shell: toolbar, explorer, tabs, editor, console/GUI panel, package modal |
| `css/styles.css` | Dark theme + responsive (mobile drawer, safe areas, widgets) |
| `js/files.js` | Virtual file system, explorer tree, icons, import/export (JSZip) |
| `js/runner.js` | Pyodide boot, pip installs, run, lint, autocomplete bridge |
| `js/editor.js` | CodeMirror 6 setup: languages, Jedi completion, Error Lens |
| `js/app.js` | UI wiring (tabs, panels, modals, run pipeline) |
| `py/tkinter_shim.py` | DOM-backed Tkinter implementation that runs inside Pyodide |

## Notes & limitations

- Pure-Python pip packages work great (`numpy`, `pandas`, `matplotlib`, `sympy`,
  `requests`, `Pillow`, `openpyxl`…). Packages requiring native binaries, raw
  sockets or threads that assume a desktop OS may not run in WebAssembly.
- Tkinter is a re-implementation mapped to HTML elements, so extremely advanced
  or exotic Tk behavior may differ — all standard beginner/intermediate widgets,
  geometry managers, variables, events, message boxes and dialogs are supported.
- `input()` uses a browser prompt (synchronous, so classic `print`/`input` scripts
  work as expected).
