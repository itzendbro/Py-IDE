/* Headless smoke test for js/editor.js.
   Stubs the CodeMirror ESM modules with a *realistic* API surface
   (EditorView class statics vs module exports are modeled correctly),
   so referencing a missing export throws — catching wiring bugs without
   needing a browser/network. Dynamic import() is redirected to stubs. */
const fs = require('fs');
const path = require('path');

const ext = { __ext: true };
const noop = () => {};

/* ---- realistic CodeMirror stubs ---- */
function FakeCompartment() {
  this.reconfigure = () => ext;
  this.of = () => ext;
}
function FakeEditorView(opts) {
  this.opts = opts;
  this.state = {
    doc: {
      length: 0, lines: 1, toString: () => '',
      line: () => ({ from: 0, to: 0, text: '' }),
      lineAt: () => ({ from: 0, to: 0, text: '' }),
    },
    selection: { main: { head: 0 }, ranges: [] },
  };
  this.dispatch = noop;
  this.focus = noop;
}
FakeEditorView.theme = () => ext;
FakeEditorView.decorations = { from: () => ext };
FakeEditorView.domEventHandlers = () => ext;
FakeEditorView.updateListener = { of: () => ext };
// NOTE: deliberately NO lineNumbers/keymap/placeholder etc. on the class,
// mirroring the real @codemirror/view API (those are module exports).

function FakeEditorState() {}
FakeEditorState.create = (cfg) => ({
  cfg,
  doc: { length: 0, lines: 1, line: () => ({ from: 0, to: 0, text: '' }), lineAt: () => ({ from: 0, to: 0, text: '' }) },
});
FakeEditorState.allowMultipleSelections = { of: () => ext };

class FakeWidgetType { constructor() {} }
const fakeDecoration = { none: ext, widget: () => ({ range: () => ext }), set: () => ext };

const stateNS = {
  EditorState: FakeEditorState,
  Compartment: FakeCompartment,
  StateField: { define: () => ext },
  StateEffect: { define: () => ({ of: () => ext }) },
};
const viewNS = {
  EditorView: FakeEditorView,
  Decoration: fakeDecoration,
  WidgetType: FakeWidgetType,
  keymap: { of: () => ext },
  lineNumbers: () => ext,
  highlightActiveLine: () => ext,
  highlightActiveLineGutter: () => ext,
  drawSelection: () => ext,
  highlightSpecialChars: () => ext,
  rectangularSelection: () => ext,
  placeholder: () => ext,
};
const commandsNS = {
  defaultKeymap: [], history: () => ext, historyKeymap: [], indentWithTab: ext,
};
const languageNS = {
  defaultHighlightStyle: {}, syntaxHighlighting: () => ext, indentOnInput: () => ext,
  bracketMatching: () => ext, closeBrackets: () => ext, closeBracketsKeymap: [],
  foldGutter: () => ext, StreamLanguage: { define: () => ext },
};
const autocompleteNS = {
  autocompletion: () => ext, completionKeymap: [], startCompletion: noop, acceptCompletion: ext,
};
const lintNS = { lintGutter: () => ext, linter: () => ext, forceLinting: noop };
const searchNS = { search: () => ext, searchKeymap: [] };
const langPyNS = { python: () => ext };
const langJsonNS = { json: () => ext };
const modesNS = {
  javascript: () => ({}), xml: () => ({}), markdown: () => ({}),
  css: {}, shell: {}, sql: () => ({}),
};

function __imp(url) {
  if (url.includes('/state')) return stateNS;
  if (url.includes('/view')) return viewNS;
  if (url.includes('/commands')) return commandsNS;
  if (url.includes('/language') || url.includes('legacy-modes')) return languageNS;
  if (url.includes('/autocomplete')) return autocompleteNS;
  if (url.includes('/lint')) return lintNS;
  if (url.includes('/search')) return searchNS;
  if (url.includes('lang-python')) return langPyNS;
  if (url.includes('lang-json')) return langJsonNS;
  if (url.includes('mode/')) return modesNS;
  throw new Error('unexpected import ' + url);
}

/* ---- minimal DOM/browser stubs ---- */
const listeners = {};
const documentStub = {
  addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
  dispatchEvent: () => true,
  getElementById: () => null,
  createElement: () => ({ classList: { add: noop, remove: noop }, style: {}, appendChild: noop }),
};
function EventStub(name) { this.type = name; }

const windowStub = {};

/* ---- load editor.js with dynamic import() redirected ---- */
let src = fs.readFileSync(path.join(__dirname, '..', 'js', 'editor.js'), 'utf8');
if (/(^|\n)\s*import\s+[\w{*]/.test(src)) {
  throw new Error('editor.js must not contain static import statements');
}
src = src.replace(/\bimport\s*\(/g, '__imp(');

const factory = new Function('window', 'document', 'console', 'Event', 'setTimeout', '__imp', src);
factory(windowStub, documentStub, console, EventStub, setTimeout, __imp);

(async () => {
  // wait for the async loadCM().then(...) chain
  await new Promise((r) => setTimeout(r, 30));
  try {
    if (typeof windowStub.IDEEditor !== 'function') {
      throw new Error('window.IDEEditor was not defined — CodeMirror load failed silently');
    }
    const mount = { appendChild: noop, querySelector: () => null };
    const ed = new windowStub.IDEEditor(mount);
    if (!ed || typeof ed.open !== 'function') throw new Error('editor instance missing methods');
    // exercise open() with a fake python file node
    const node = { name: 'main.py', content: 'print(1)\n' };
    ed.open(node);
    await new Promise((r) => setTimeout(r, 10));
    ed.insertText('(', 1);
    ed.dedent();
    ed.clearLens();
    ed.forceLint();
    console.log('PASS  editor.js constructs and operates with realistic CM stubs');
  } catch (e) {
    console.error('FAIL  editor.js:', e.message);
    process.exit(1);
  }
})();
