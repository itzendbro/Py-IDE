/* ============================================================
   editor.js — CodeMirror 6 editor (classic script; no ES-module
   build needed so index.html works straight from file://).
   • multi-language syntax (python/json/js/html/css/md/...)
   • async autocomplete via Jedi (pyodide) + keywords fallback
   • Error-Lens style inline diagnostics + squiggles + gutter
   Defines window.IDEEditor and fires "ide-editor-ready" once the
   CodeMirror modules have loaded from the CDN.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- Python keyword / builtin fallback completions ---------- */
  const PY_WORDS = `
False None True and as assert async await break class continue def del elif else
except finally for from global if import in is lambda nonlocal not or pass raise
return try while with yield self
abs all any bin bool bytearray bytes callable chr classmethod complex dict dir divmod
enumerate eval exec filter float format frozenset getattr globals hasattr hash hex id
input int isinstance issubclass iter len list locals map max min next object oct open
ord pow print property range repr reversed round set setattr slice sorted staticmethod
str sum super tuple type vars zip __name__ __file__
`.trim().split(/\s+/);
  const KEYWORD_OPTS = PY_WORDS.map((w) => {
    const isKw = /^(False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)$/.test(w);
    return { label: w, type: isKw ? 'keyword' : 'builtin', detail: isKw ? 'keyword' : 'built-in' };
  });

  const JEDI_TYPES = {
    function: 'function', method: 'method', class: 'class', module: 'namespace',
    keyword: 'keyword', statement: 'variable', instance: 'variable',
    property: 'property', param: 'variable', path: 'namespace',
    'function annotation': 'function',
  };

  // shared editor state (no CodeMirror dependency)
  let currentNode = null;

  async function loadCM() {
    return Promise.all([
      import('https://esm.sh/@codemirror/state@6'),
      import('https://esm.sh/@codemirror/view@6'),
      import('https://esm.sh/@codemirror/commands@6'),
      import('https://esm.sh/@codemirror/language@6'),
      import('https://esm.sh/@codemirror/autocomplete@6'),
      import('https://esm.sh/@codemirror/lint@6'),
      import('https://esm.sh/@codemirror/search@6'),
    ]);
  }

  async function build() {
    const [
      modState, modView, modCommands, modLanguage, modAutocomplete, modLint, modSearch,
    ] = await loadCM();

    // Correct module destructuring (these are module exports, NOT class statics).
    const { EditorState, Compartment, StateField, StateEffect } = modState;
    const {
      EditorView, Decoration, WidgetType, keymap, lineNumbers,
      highlightActiveLine, highlightActiveLineGutter, drawSelection,
      highlightSpecialChars, rectangularSelection, placeholder,
    } = modView;
    const { defaultKeymap, history, historyKeymap, indentWithTab } = modCommands;
    const {
      defaultHighlightStyle, syntaxHighlighting, indentOnInput,
      bracketMatching, closeBrackets, closeBracketsKeymap, foldGutter, StreamLanguage,
    } = modLanguage;
    const { autocompletion, completionKeymap, startCompletion, acceptCompletion } = modAutocomplete;
    const { lintGutter, linter, forceLinting } = modLint;
    const { search: searchExt, searchKeymap } = modSearch;

    /* ---------- Error-Lens inline widget ---------- */
    class LensWidget extends WidgetType {
      constructor(text, cls) { super(); this.text = text; this.cls = cls; }
      toDOM() {
        const s = document.createElement('span');
        s.className = 'error-lens ' + this.cls;
        s.textContent = this.text;
        return s;
      }
      ignoreEvent() { return true; }
    }

    const setLens = StateEffect.define();
    const lensField = StateField.define({
      create() { return Decoration.none; },
      update(deco, tr) {
        deco = deco.map(tr.changes);
        for (const e of tr.effects) {
          if (e.is(setLens)) deco = buildLens(tr.state, e.value);
        }
        return deco;
      },
      provide: (f) => EditorView.decorations.from(f),
    });

    function buildLens(state, diags) {
      const byLine = new Map();
      for (const d of diags) {
        if (d.from >= state.doc.length) continue;
        const line = state.doc.lineAt(Math.max(0, d.from));
        if (!byLine.has(line.number)) byLine.set(line.number, []);
        byLine.get(line.number).push(d);
      }
      const decos = [];
      for (const [ln, ds] of byLine) {
        const line = state.doc.line(ln);
        const pos = Math.min(line.to, state.doc.length);
        const msg = ds.map((d) => d.message).join('   \u00b7   ');
        const cls = ds.some((d) => d.severity === 'error') ? 'err' : 'warn';
        decos.push(Decoration.widget({ widget: new LensWidget(msg, cls), side: -1 }).range(pos));
      }
      decos.sort((a, b) => a.from - b.from);
      return Decoration.set(decos);
    }

    /* ---------- lint / Error Lens source ---------- */
    function pyLintSource(view) {
      const node = currentNode;
      if (!node || !node.name.toLowerCase().endsWith('.py')) return Promise.resolve([]);
      if (!window.Runner || !window.Runner.isReady() || window.Runner.isBusy()) return Promise.resolve([]);
      const code = view.state.doc.toString();
      const path = '/home/pyodide/project/' + window.Files.pathOf(node);
      return window.Runner.lint(code, path).then((raw) => {
        raw = raw || [];
        const diags = raw.map((d) => {
          const [sev, lineno, col, msg] = d;
          const lines = view.state.doc.lines;
          const ln = Math.min(Math.max(1, lineno), lines);
          const line = view.state.doc.line(ln);
          const from = line.from + Math.min(Math.max(0, col), Math.max(0, line.text.length));
          let to;
          if (col <= 0) {
            to = line.to;
          } else {
            const mm = line.text.slice(col).match(/^(\w+)/);
            to = Math.min(from + (mm ? mm[1].length : 1), line.to);
          }
          return {
            from, to,
            severity: sev === 'error' ? 'error' : 'warning',
            message: String(msg),
            source: 'pyflakes',
          };
        });
        if (currentNode === node) {
          try { view.dispatch({ effects: setLens.of(diags) }); } catch (e) {}
        }
        return diags;
      }).catch(() => []);
    }

    /* ---------- completion sources ---------- */
    function pythonSource(ctx) {
      const word = ctx.matchBefore(/[\w.]*/);
      if (!word || (word.from === word.to && !ctx.explicit)) return null;
      const node = currentNode;
      const code = ctx.state.doc.toString();
      const pos = ctx.state.selection.main.head;
      const line = ctx.state.doc.lineAt(pos);
      const rel = node ? window.Files.pathOf(node) : 'main.py';
      const fpath = '/home/pyodide/project/' + rel;
      const li = line.number;
      const col = pos - line.from;

      const fallback = { from: word.from, options: KEYWORD_OPTS, validFor: /^[\w.]*$/ };

      if (!window.Runner || !window.Runner.isReady() || window.Runner.isBusy()) return fallback;

      return window.Runner.complete(code, fpath, li, col).then((comps) => {
        let opts = (comps || []).map((c) => ({
          label: c[0],
          type: JEDI_TYPES[c[1]] || 'variable',
          detail: c[2] && c[2] !== c[0] ? c[2] : undefined,
          info: c[3] || undefined,
        }));
        const have = new Set(opts.map((o) => o.label));
        for (const k of KEYWORD_OPTS) {
          if (!have.has(k.label) && k.label.startsWith('_') === false) opts.push(k);
        }
        if (!opts.length) opts = KEYWORD_OPTS;
        return { from: word.from, options: opts, validFor: /^[\w.]*$/ };
      }).catch(() => fallback);
    }

    function documentWords(ctx) {
      const word = ctx.matchBefore(/[\w-]+/);
      if (!word || (word.from === word.to && !ctx.explicit)) return null;
      const text = ctx.state.doc.toString();
      const seen = new Map();
      const re = /[A-Za-z_][\w-]*/g;
      let m;
      while ((m = re.exec(text))) seen.set(m[0], (seen.get(m[0]) || 0) + 1);
      const options = [...seen.entries()]
        .map(([label, boost]) => ({ label, type: 'variable', boost }))
        .filter((o) => o.label !== word.text);
      return { from: word.from, options, validFor: /^[\w-]*$/ };
    }

    function completionSource(ctx) {
      const node = currentNode;
      const isPy = node && node.name.split('.').pop().toLowerCase() === 'py';
      return isPy ? pythonSource(ctx) : documentWords(ctx);
    }

    const dotTrigger = EditorView.domEventHandlers({
      keydown(event, view) {
        if (event.key === '.') {
          setTimeout(() => { try { startCompletion(view); } catch (e) {} }, 30);
        }
        return false;
      },
    });

    /* ---------- theme ---------- */
    const darkThemeSpec = {
      '&': { color: '#e6e7ea', backgroundColor: '#17181d', height: '100%' },
      '.cm-content': { caretColor: '#4f8cff', padding: '8px 0 40px 0' },
      '.cm-line': { padding: '0 10px' },
      '.cm-gutters': {
        backgroundColor: '#17181d', color: '#6b707d', border: 'none',
        borderRight: '1px solid #34363f',
      },
      '.cm-activeLine': { backgroundColor: 'rgba(255,255,255,0.035)' },
      '.cm-activeLineGutter': { backgroundColor: 'rgba(255,255,255,0.06)', color: '#9aa0ad' },
      '.cm-cursor': { borderLeftColor: '#4f8cff', borderLeftWidth: '2px' },
      '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
        { backgroundColor: 'rgba(79,140,255,0.25) !important' },
      '.cm-selectionMatch': { backgroundColor: 'rgba(79,140,255,0.18)' },
      '.cm-matchingBracket': { backgroundColor: 'rgba(79,140,255,0.25)', outline: '1px solid rgba(79,140,255,0.4)' },
      '.cm-foldPlaceholder': { backgroundColor: '#2e303a', border: '1px solid #34363f', color: '#9aa0ad' },
    };

    /* ---------- language loading ---------- */
    const langCache = new Map();
    async function langFor(name) {
      const ext = (name.split('.').pop() || '').toLowerCase();
      if (langCache.has(ext)) return langCache.get(ext);
      let langExt = null;
      try {
        switch (ext) {
          case 'py': case 'pyw': {
            const m = await import('https://esm.sh/@codemirror/lang-python@6');
            langExt = m.python();
            break;
          }
          case 'json': {
            const m = await import('https://esm.sh/@codemirror/lang-json@6');
            langExt = m.json();
            break;
          }
          case 'js': case 'mjs': case 'cjs': case 'jsx': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/javascript');
            langExt = StreamLanguage.define(m.javascript({}));
            break;
          }
          case 'ts': case 'tsx': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/javascript');
            langExt = StreamLanguage.define(m.javascript({ typescript: true }));
            break;
          }
          case 'css': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/css');
            langExt = StreamLanguage.define(m.css);
            break;
          }
          case 'html': case 'htm': case 'vue': case 'xml': case 'svg': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/xml');
            langExt = StreamLanguage.define(m.xml({}));
            break;
          }
          case 'md': case 'markdown': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/markdown');
            langExt = StreamLanguage.define(m.markdown({}));
            break;
          }
          case 'sh': case 'bash': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/shell');
            langExt = StreamLanguage.define(m.shell);
            break;
          }
          case 'sql': {
            const m = await import('https://esm.sh/@codemirror/legacy-modes@6/mode/sql');
            langExt = StreamLanguage.define(m.sql({}));
            break;
          }
          default:
            langExt = [];
        }
      } catch (e) {
        console.warn('language load failed', ext, e);
        langExt = [];
      }
      langCache.set(ext, langExt);
      return langExt;
    }

    /* ---------- editor class ---------- */
    class IDEEditor {
      constructor(mount) {
        this.mount = mount;
        this.langComp = new Compartment();
        const self = this;

        this.view = new EditorView({
          parent: mount,
          state: EditorState.create({
            doc: '',
            extensions: [
              lineNumbers(),
              highlightSpecialChars(),
              history(),
              foldGutter(),
              drawSelection(),
              EditorState.allowMultipleSelections.of(true),
              indentOnInput(),
              bracketMatching(),
              closeBrackets(),
              autocompletion({
                override: [completionSource],
                activateOnTyping: true,
                icons: true,
                tooltipClass: () => 'cm-ac-tooltip',
              }),
              dotTrigger,
              lintGutter(),
              linter(pyLintSource, { delay: 550, tooltips: true }),
              highlightActiveLine(),
              highlightActiveLineGutter(),
              rectangularSelection(),
              searchExt({ top: true }),
              syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
              EditorView.theme(darkThemeSpec, { dark: true }),
              lensField,
              placeholder('Open or create a file from the explorer (📄+)…'),
              this.langComp.of([]),
              keymap.of([
                // Note: Mod-Enter is handled globally in app.js (avoids double-runs)
                { key: 'Mod-s', run: () => { window.Files && window.Files.save(); return true; } },
                { key: 'Tab', run: acceptCompletion },
                ...closeBracketsKeymap,
                ...defaultKeymap,
                ...searchKeymap,
                ...historyKeymap,
                ...completionKeymap,
                indentWithTab,
              ]),
              EditorView.updateListener.of((u) => {
                if (u.docChanged && self.onChange) self.onChange(self.view.state.doc.toString());
                if (u.selectionSet && self.onCursor) {
                  const pos = u.state.selection.main.head;
                  const line = u.state.doc.lineAt(pos);
                  self.onCursor(line.number, pos - line.from + 1);
                }
              }),
            ],
          }),
        });
      }

      open(node) {
        currentNode = node;
        const doc = node.content || '';
        this.view.dispatch({
          changes: { from: 0, to: this.view.state.doc.length, insert: doc },
          effects: this.langComp.reconfigure([]),
        });
        this.clearLens();
        langFor(node.name).then((langExt) => {
          if (currentNode !== node) return;
          this.view.dispatch({ effects: this.langComp.reconfigure(langExt) });
          try { forceLinting(this.view); } catch (e) {}
        });
        try { forceLinting(this.view); } catch (e) {}
        this.view.focus();
      }

      get content() { return this.view.state.doc.toString(); }

      forceLint() { try { forceLinting(this.view); } catch (e) {} }

      clearLens() { this.view.dispatch({ effects: setLens.of([]) }); }

      focus() { try { this.view.focus(); } catch (e) {} }

      insertText(text, moveBack = 0) {
        const view = this.view;
        const changes = [];
        const sel = view.state.selection;
        for (const r of sel.ranges) changes.push({ from: r.from, to: r.to, insert: text });
        if (!changes.length) changes.push({ from: view.state.doc.length, insert: text });
        view.dispatch({
          changes,
          selection: sel.ranges.map((r) => {
            const end = r.from + text.length;
            const p = Math.max(r.from, end - moveBack);
            return { anchor: p, head: p };
          }),
          scrollIntoView: true,
        });
        view.focus();
      }

      dedent() {
        const view = this.view;
        const { from } = view.state.selection.main;
        const line = view.state.doc.lineAt(from);
        const extra = Math.min(4, line.text.length - line.text.trimStart().length);
        if (extra > 0) {
          view.dispatch({ changes: { from: line.from, to: line.from + extra, insert: '' } });
        }
        view.focus();
      }
    }

    window.IDEEditor = IDEEditor;
    document.dispatchEvent(new Event('ide-editor-ready'));
  }

  build().catch((e) => {
    console.error('CodeMirror failed to load:', e);
    const mount = document.getElementById('editor');
    if (mount) {
      mount.innerHTML =
        '<div class="empty-state"><div class="big">⚠️</div>' +
        '<div class="hint">The editor components could not be loaded from the CDN.<br>' +
        'Check your internet connection and reload the page.</div></div>';
    }
  });
})();
