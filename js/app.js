/* ============================================================
   app.js — UI wiring: tabs, panels, explorer actions,
   pip modal, import/export, run/lint pipeline.
   ES module (uses ./editor.js which imports CodeMirror).
   ============================================================ */
import IDEEditor from './editor.js';

/* ---------------- console ---------------- */
const consoleEl = document.getElementById('console');
function writeOut(text, cls) {
  const line = document.createElement('div');
  line.className = 'c-line c-' + (cls || 'out');
  line.textContent = text;
  consoleEl.appendChild(line);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

/* ---------------- GUI panel switching ---------------- */
function showTab(name) {
  document.querySelectorAll('.panel-tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  document.getElementById('consolePane').classList.toggle('active', name === 'console');
  document.getElementById('guiPane').classList.toggle('active', name === 'gui');
  const panel = document.getElementById('panel');
  if (panel.classList.contains('collapsed')) panel.classList.remove('collapsed');
}
globalThis.__tkShow = () => showTab('gui');

/* ---------------- tabs state ---------------- */
const openTabs = [];   // node ids
let activeId = null;
let editor = null;

function getActiveNode() {
  return openTabs.length ? window.Files.getNode(activeId) : null;
}

/* ---------------- editor callbacks ---------------- */
function showEmptyState(show) {
  const mount = document.getElementById('editor');
  let es = mount.querySelector('.empty-state');
  if (show && !es) {
    es = document.createElement('div');
    es.className = 'empty-state';
    es.innerHTML = `<div class="big">🐍</div>
      <div class="hint">
        Welcome to <b>Py-IDE</b> — Python runs in your browser (WebAssembly).<br><br>
        <b>📄+</b> new file &nbsp;·&nbsp; <b>⬆ Import</b> files or a folder &nbsp;·&nbsp; <b>▶ Run</b> or press <code>Ctrl+Enter</code><br>
        Autocomplete <code>.</code> triggers suggestions · inline errors like VS Code's Error Lens.<br>
        <b>pip install</b> works (📦 Pip) · <b>tkinter</b> GUIs render in the GUI Preview tab.
      </div>`;
    mount.appendChild(es);
  } else if (!show && es) {
    es.remove();
  }
}

function renderTabs() {
  const tabsEl = document.getElementById('tabs');
  tabsEl.innerHTML = '';
  const files = openTabs.map((id) => window.Files.getNode(id)).filter(Boolean);

  showEmptyState(!files.length);

  for (const node of files) {
    const t = document.createElement('div');
    t.className = 'tab' + (node.id === activeId ? ' active' : '');
    const ic = document.createElement('span');
    ic.innerHTML = window.Files.iconFor(node.name);
    const nm = document.createElement('span');
    nm.className = 'tname';
    nm.textContent = node.name;
    const x = document.createElement('button');
    x.className = 'x';
    x.textContent = '✕';
    x.title = 'Close';
    x.addEventListener('click', (e) => {
      e.stopPropagation();
      closeTab(node.id);
    });
    t.appendChild(ic);
    t.appendChild(nm);
    t.appendChild(x);
    t.addEventListener('click', () => switchTab(node.id));
    tabsEl.appendChild(t);
  }
}

function openNode(node) {
  if (node.type !== 'file') return;
  // save current before switching
  saveActiveContent();
  if (!openTabs.includes(node.id)) openTabs.push(node.id);
  activeId = node.id;
  renderTabs();
  const es = document.getElementById('editor').querySelector('.empty-state');
  if (es) es.remove();
  editor.open(node);
  updateStatusLang(node.name);
  scheduleLint(node);
}

function switchTab(id) {
  saveActiveContent();
  activeId = id;
  renderTabs();
  const node = window.Files.getNode(id);
  if (node) {
    editor.open(node);
    updateStatusLang(node.name);
    scheduleLint(node);
  }
}

function closeTab(id) {
  saveActiveContent();
  const idx = openTabs.indexOf(id);
  if (idx >= 0) openTabs.splice(idx, 1);
  if (activeId === id) {
    activeId = openTabs[Math.min(idx, openTabs.length - 1)] || null;
  }
  renderTabs();
  const node = activeId ? window.Files.getNode(activeId) : null;
  if (node) {
    editor.open(node);
    updateStatusLang(node.name);
    scheduleLint(node);
  } else {
    document.getElementById('stLang').textContent = '—';
    document.getElementById('stPos').textContent = 'Ln 1, Col 1';
    editor.view.dispatch({ changes: { from: 0, to: editor.view.state.doc.length, insert: '' } });
    editor.clearLens();
  }
}

function saveActiveContent() {
  const node = getActiveNode();
  if (node && editor) node.content = editor.content;
}

/* ---------------- linting (CodeMirror linter source drives squiggles,
   gutter markers, hover messages and the inline Error Lens) ---------------- */
let lintTimer = null;
function scheduleLint(node) {
  clearTimeout(lintTimer);
  const target = node || getActiveNode();
  if (!target || !target.name.toLowerCase().endsWith('.py')) {
    if (editor) editor.clearLens();
    return;
  }
  if (!window.Runner.isReady()) return;
  lintTimer = setTimeout(() => { if (editor && getActiveNode() === target) editor.forceLint(); }, 60);
}

/* ---------------- status bar ---------------- */
const stPython = document.getElementById('stPython');
const stLang = document.getElementById('stLang');
const stPos = document.getElementById('stPos');
function updateStatusLang(name) {
  const ext = (name.split('.').pop() || '').toUpperCase();
  stLang.textContent = ext || '—';
}

/* ---------------- runner hooks ---------------- */
window.Runner.setHooks({
  out: writeOut,
  status: (s) => { stPython.textContent = '⏳ ' + s; },
  onReady: () => {
    stPython.textContent = '🟢 Python ready';
    scheduleLint(getActiveNode());
  },
  guiShow: () => showTab('gui'),
});

/* ---------------- run ---------------- */
async function runActive() {
  saveActiveContent();
  window.Files.save();
  let node = getActiveNode();
  if (!node) {
    writeOut('Open a file to run (create 📄+ a main.py first).', 'sys');
    return;
  }
  if (!node.name.toLowerCase().endsWith('.py')) {
    writeOut('Only Python (.py) files can run. Open a .py file.', 'sys');
    return;
  }
  showTab('console');
  await window.Runner.run(node);
  scheduleLint(node);
}
window.IDE = { runActive };

/* ---------------- editor init ---------------- */
editor = new IDEEditor(document.getElementById('editor'));
let saveTimer = null;
editor.onChange = (text) => {
  const node = getActiveNode();
  if (node) {
    node.content = text;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => window.Files.save(), 400);
  }
};
editor.onCursor = (ln, col) => {
  stPos.textContent = 'Ln ' + ln + ', Col ' + col;
};

/* ---------------- files hooks ---------------- */
window.Files.onOpen = (node) => openNode(node);
window.Files.onDeleted = (id) => {
  const idx = openTabs.indexOf(id);
  if (idx >= 0) closeTab(id);
};
window.Files.onRenamed = (node) => {
  if (openTabs.includes(node.id)) {
    renderTabs();
    updateStatusLang(node.name);
  }
};
window.Files.onImported = (count) => {
  writeOut('📥 Imported ' + count + ' file(s).', 'ok');
};
window.Files.onMobileOpen = () => {
  document.getElementById('explorer').classList.remove('open');
  document.getElementById('backdrop').classList.remove('show');
};

/* ---------------- default project ---------------- */
const DEFAULT_MAIN = `# Welcome to Py-IDE 🐍  (Run with the ▶ button or Ctrl+Enter)
#
# Everything runs in your browser with WebAssembly (Pyodide):
#   • print / input  • pip packages (📦 Pip)  • tkinter GUIs (GUI Preview tab)

print("Hello from Python in your browser!")

name = input("What is your name? ")
print("Nice to meet you,", name, "👋")

# --- Tkinter demo: uncomment to see a real GUI window ---
# import tkinter as tk
# from tkinter import messagebox
#
# root = tk.Tk()
# root.title("My first GUI")
# root.geometry("320x180")
#
# count = tk.IntVar(value=0)
#
# def clicked():
#     count.set(count.get() + 1)
#     if count.get() == 5:
#         messagebox.showinfo("Wow", "You clicked 5 times! 🎉")
#
# tk.Label(root, text="Tkinter works in the browser!").pack(pady=12)
# tk.Button(root, text="Click me", command=clicked).pack()
# tk.Label(root, textvariable=count).pack(pady=10)
#
# root.mainloop()
`;

const defaultTree = window.Files.makeNode('project', 'folder');
const mainFile = window.Files.makeNode('main.py', 'file', DEFAULT_MAIN);
defaultTree.children.push(mainFile);

window.Files.init(document.getElementById('tree'), defaultTree);
renderTabs();
// open main.py by default
openNode(mainFile);

/* ---------------- top bar buttons ---------------- */
document.getElementById('runBtn').addEventListener('click', runActive);

document.getElementById('explorerToggle').addEventListener('click', () => {
  const ex = document.getElementById('explorer');
  const bd = document.getElementById('backdrop');
  ex.classList.toggle('open');
  bd.classList.toggle('show');
});
document.getElementById('backdrop').addEventListener('click', () => {
  document.getElementById('explorer').classList.remove('open');
  document.getElementById('backdrop').classList.remove('show');
});

document.getElementById('newFileBtn').addEventListener('click', () => window.Files.newFile());
document.getElementById('newFolderBtn').addEventListener('click', () => window.Files.newFolder());

/* dropdowns */
function wireDropdown(btnId, menuId) {
  const btn = document.getElementById(btnId);
  const menu = document.getElementById(menuId);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.dropdown-menu').forEach((m) => { if (m !== menu) m.classList.remove('open'); });
    menu.classList.toggle('open');
  });
  menu.addEventListener('click', (e) => e.stopPropagation());
}
wireDropdown('importBtn', 'importMenu');
wireDropdown('exportBtn', 'exportMenu');
document.addEventListener('click', () => {
  document.querySelectorAll('.dropdown-menu').forEach((m) => m.classList.remove('open'));
});

document.getElementById('importMenu').addEventListener('click', (e) => {
  const a = e.target.closest('button[data-action]');
  if (!a) return;
  if (a.dataset.action === 'import-files') document.getElementById('fileInput').click();
  if (a.dataset.action === 'import-folder') document.getElementById('folderInput').click();
});
document.getElementById('fileInput').addEventListener('change', (e) => {
  window.Files.importFiles(e.target.files);
  e.target.value = '';
});
document.getElementById('folderInput').addEventListener('change', (e) => {
  window.Files.importFiles(e.target.files);
  e.target.value = '';
});

document.getElementById('exportMenu').addEventListener('click', async (e) => {
  const a = e.target.closest('button[data-action]');
  if (!a) return;
  saveActiveContent();
  window.Files.save();
  if (a.dataset.action === 'export-zip') await window.Files.exportZip();
  if (a.dataset.action === 'export-file') window.Files.exportFile(getActiveNode());
});

/* panel tabs + toggle */
document.querySelectorAll('.panel-tab').forEach((b) => {
  b.addEventListener('click', () => showTab(b.dataset.tab));
});
document.getElementById('clearConsoleBtn').addEventListener('click', () => {
  consoleEl.innerHTML = '';
});
document.getElementById('panelToggle').addEventListener('click', () => {
  document.getElementById('panel').classList.toggle('collapsed');
});

/* ---------------- pip modal ---------------- */
const pkgModal = document.getElementById('pkgModal');
const pkgInput = document.getElementById('pkgInput');
const pkgList = document.getElementById('pkgList');
const CHIPS = ['numpy', 'pandas', 'matplotlib', 'sympy', 'requests', 'openpyxl', 'Pillow', 'scipy', 'scikit-learn', 'networkx'];

function renderPkg() {
  const pkgs = window.Runner.packages();
  pkgList.innerHTML = '';
  const builtin = document.createElement('li');
  builtin.innerHTML = '<span class="pname">tkinter (built-in browser GUI)</span><span style="color:var(--green)">✓ ready</span>';
  pkgList.appendChild(builtin);
  if (!pkgs.length) {
    const li = document.createElement('li');
    li.style.color = 'var(--text-faint)';
    li.textContent = 'No extra packages installed yet.';
    pkgList.appendChild(li);
  }
  for (const p of pkgs) {
    const li = document.createElement('li');
    const nm = document.createElement('span');
    nm.className = 'pname';
    nm.textContent = p;
    const ok = document.createElement('span');
    ok.style.color = 'var(--green)';
    ok.textContent = '✓ installed';
    li.appendChild(nm);
    li.appendChild(ok);
    pkgList.appendChild(li);
  }
}

async function doInstall(name) {
  name = (name || pkgInput.value).trim();
  if (!name) return;
  pkgInput.value = '';
  showTab('console');
  pkgModal.classList.add('hidden');
  writeOut('📦 pip install ' + name + ' …', 'sys');
  try {
    const ok = await window.Runner.installPackage(name);
    if (ok) writeOut('✅ ' + name + ' installed.', 'ok');
  } catch (e) {
    writeOut('❌ ' + (e.message || e), 'err');
  }
  renderPkg();
}

document.getElementById('pkgBtn').addEventListener('click', () => {
  renderPkg();
  pkgModal.classList.remove('hidden');
});
document.getElementById('pkgCloseBtn').addEventListener('click', () => pkgModal.classList.add('hidden'));
pkgModal.addEventListener('click', (e) => { if (e.target === pkgModal) pkgModal.classList.add('hidden'); });
document.getElementById('pkgInstallBtn').addEventListener('click', () => doInstall());
pkgInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doInstall(); });

const chipsEl = document.getElementById('pkgChips');
for (const c of CHIPS) {
  const b = document.createElement('button');
  b.className = 'chip';
  b.textContent = c;
  b.addEventListener('click', () => doInstall(c));
  chipsEl.appendChild(b);
}

/* ---------------- mobile extra-keys bar ---------------- */
document.getElementById('keybar').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.act === 'run') { runActive(); return; }
  if (b.dataset.act === 'dedent') { editor.dedent(); return; }
  if (b.dataset.ins !== undefined) {
    editor.insertText(b.dataset.ins, parseInt(b.dataset.move || '0', 10));
  }
});

/* ---------------- boot Python (non-blocking) ---------------- */
writeOut('Py-IDE started. Booting Python runtime (first run downloads ~10MB from CDN)…', 'sys');
setTimeout(() => window.Runner.boot(), 100);

/* keyboard: Ctrl/Cmd+Enter handled in editor; also global fallback */
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    runActive();
  }
});
