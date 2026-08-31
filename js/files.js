/* ============================================================
   files.js — virtual file system, explorer tree, import/export
   Exposes window.Files
   ============================================================ */
(function () {
  'use strict';

  const LS_KEY = 'pyide_project_v2';
  let uid = 1;
  const nid = () => 'n' + uid++;

  function makeNode(name, type, content) {
    const n = { id: nid(), name, type };
    if (type === 'folder') n.children = [];
    else n.content = content || '';
    return n;
  }

  // ---------- icons ----------
  const FOLDER_SVG = `<svg viewBox="0 0 24 24"><path d="M3 6.8C3 5.8 3.8 5 4.8 5h4.2c.5 0 .9.2 1.2.6l1.2 1.5h7.8c1 0 1.8.8 1.8 1.8v8.3c0 1-.8 1.8-1.8 1.8H4.8c-1 0-1.8-.8-1.8-1.8V6.8z" fill="#e0b863" stroke="#b98a2e" stroke-width="1"/></svg>`;
  const FILE_SVG = `<svg viewBox="0 0 24 24"><path d="M6 2.8h7.6L19 8.2v11c0 1.1-.9 2-2 2H6c-1.1 0-2-.9-2-2v-14.4c0-1.1.9-2 2-2z" fill="#8b93a3"/><path d="M13.6 2.8V8.2H19z" fill="#aeb6c4"/></svg>`;

  // extension -> [badge class, label]
  const BADGES = {
    py: ['fi-py', null], // special two-tone
    pyw: ['fi-py', null],
    json: ['fi-json', '{}'],
    js: ['fi-js', 'JS'],
    mjs: ['fi-js', 'JS'],
    cjs: ['fi-js', 'JS'],
    ts: ['fi-ts', 'TS'],
    html: ['fi-html', '<>'],
    htm: ['fi-html', '<>'],
    css: ['fi-css', '#'],
    md: ['fi-md', 'M↓'],
    markdown: ['fi-md', 'M↓'],
    txt: ['fi-txt', 'TXT'],
    text: ['fi-txt', 'TXT'],
    csv: ['fi-csv', 'CSV'],
    tsv: ['fi-csv', 'TSV'],
    xml: ['fi-xml', 'XML'],
    yml: ['fi-yml', 'YML'],
    yaml: ['fi-yml', 'YML'],
    toml: ['fi-cfg', 'TOML'],
    ini: ['fi-cfg', 'INI'],
    cfg: ['fi-cfg', 'CFG'],
    conf: ['fi-cfg', 'CONF'],
    sh: ['fi-sh', 'SH'],
    bash: ['fi-sh', 'SH'],
    sql: ['fi-sql', 'SQL'],
    png: ['fi-img', 'IMG'],
    jpg: ['fi-img', 'IMG'],
    jpeg: ['fi-img', 'IMG'],
    gif: ['fi-img', 'IMG'],
    webp: ['fi-img', 'IMG'],
    svg: ['fi-img', 'IMG'],
    ico: ['fi-img', 'IMG'],
    pdf: ['fi-pdf', 'PDF'],
    zip: ['fi-zip', 'ZIP'],
    tar: ['fi-zip', 'TAR'],
    gz: ['fi-zip', 'GZ'],
    c: ['fi-c', 'C'],
    h: ['fi-c', 'H'],
    cpp: ['fi-c', 'C++'],
    jsx: ['fi-js', 'JSX'],
    tsx: ['fi-ts', 'TSX'],
    lock: ['fi-lock', '🔒'],
  };

  function iconFor(name) {
    const dot = name.lastIndexOf('.');
    const ext = dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
    const base = name.toLowerCase();
    if (base === 'dockerfile') return `<span class="fi fi-cfg">DK</span>`;
    if (base === 'makefile') return `<span class="fi fi-cfg">MK</span>`;
    if (base.endsWith('requirements.txt') || base === 'requirements') return `<span class="fi fi-py"><span class="l1">R</span><span class="l2">q</span></span>`;
    const b = BADGES[ext];
    if (!b) return `<span class="fi fi-unknown">${FILE_SVG}</span>`;
    const [cls, label] = b;
    if (cls === 'fi-py') return `<span class="fi fi-py"><span class="l1">P</span><span class="l2">y</span></span>`;
    return `<span class="fi ${cls}">${label}</span>`;
  }

  // ---------- state ----------
  let root = { id: nid(), name: 'project', type: 'folder', children: [] };
  let selectedId = null;
  let openSet = new Set();
  const nodeById = new Map();

  function indexNodes() {
    nodeById.clear();
    (function walk(n) {
      nodeById.set(n.id, n);
      if (n.children) n.children.forEach(walk);
    })(root);
  }

  function pathOf(node) {
    // build path by searching
    const parts = [];
    let cur = node;
    while (cur && cur !== root) { parts.unshift(cur.name); cur = parentOf(cur); }
    return parts.join('/');
  }

  function parentOf(node) {
    let found = null;
    (function walk(n) {
      if (n.children) {
        for (const c of n.children) {
          if (c === node) { found = n; return; }
          walk(c);
        }
      }
    })(root);
    return found;
  }

  function findByPath(path) {
    if (!path) return root;
    const parts = path.split('/').filter(Boolean);
    let cur = root;
    for (const p of parts) {
      if (!cur.children) return null;
      cur = cur.children.find((c) => c.name === p);
      if (!cur) return null;
    }
    return cur;
  }

  function save() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(root));
    } catch (e) {
      console.warn('persist failed', e);
    }
  }

  function load(defaultTree) {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        root = JSON.parse(raw);
        // re-index ids in case
        uid = 1;
        (function reId(n) {
          n.id = nid();
          if (n.children) n.children.forEach(reId);
        })(root);
      } else if (defaultTree) {
        root = defaultTree;
      }
    } catch (e) {
      console.warn('load failed', e);
      if (defaultTree) root = defaultTree;
    }
    indexNodes();
    openSet.add(root.id);
  }

  // ---------- mutations ----------
  function selectedFolder() {
    const n = nodeById.get(selectedId);
    if (n && n.type === 'folder') return n;
    if (n && n.type === 'file') {
      const p = parentOf(n);
      return p || root;
    }
    return root;
  }

  function createEntry(type) {
    const isFile = type === 'file';
    const label = isFile ? 'New file name (e.g. app.py, utils/data.json)' : 'New folder name';
    const name = window.prompt(label);
    if (!name) return;
    const parts = name.trim().split('/').filter(Boolean);
    if (!parts.length) return;
    let parent = selectedFolder();
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const last = i === parts.length - 1;
      if (last && isFile) {
        if (parent.children.some((c) => c.name === part)) { alert('That name already exists.'); return; }
        const node = makeNode(part, 'file', '');
        parent.children.push(node);
        openSet.add(parent.id);
        save(); renderTree();
        if (window.Files.onOpen) window.Files.onOpen(node);
        return;
      } else {
        let dir = parent.children.find((c) => c.type === 'folder' && c.name === part);
        if (!dir) {
          if (parent.children.some((c) => c.name === part)) { alert('Name conflict: ' + part); return; }
          dir = makeNode(part, 'folder');
          parent.children.push(dir);
        }
        openSet.add(dir.id);
        parent = dir;
      }
    }
    save(); renderTree();
  }

  function remove(node) {
    if (!node || node === root) return;
    const label = node.type === 'folder'
      ? `Delete folder "${node.name}" and everything inside it?`
      : `Delete file "${node.name}"?`;
    if (!window.confirm(label)) return;
    const p = parentOf(node);
    p.children = p.children.filter((c) => c !== node);
    if (selectedId === node.id) selectedId = null;
    save();
    renderTree();
    if (window.Files.onDeleted) window.Files.onDeleted(node.id);
  }

  function rename(node) {
    if (!node || node === root) return;
    const name = window.prompt('Rename to:', node.name);
    if (!name || name.trim() === node.name) return;
    const p = parentOf(node);
    if (p.children.some((c) => c !== node && c.name === name.trim())) { alert('That name already exists.'); return; }
    node.name = name.trim();
    save();
    renderTree();
    if (window.Files.onRenamed) window.Files.onRenamed(node);
  }

  // ---------- tree rendering ----------
  let treeEl = null;
  function renderTree() {
    if (!treeEl) return;
    treeEl.innerHTML = '';
    root.children.forEach((n) => renderNode(n, 0, treeEl));
    if (!root.children.length) {
      treeEl.innerHTML = `<div style="padding:14px 10px;color:var(--text-faint);font-size:12px;line-height:1.7">
        No files yet.<br>Tap 📄+ to create a file,<br>or ⬆ Import to add files.</div>`;
    }
  }

  function renderNode(node, depth, container) {
    const row = document.createElement('div');
    row.className = 'tree-row' + (node.type === 'folder' && openSet.has(node.id) ? ' open' : '') +
      (selectedId === node.id ? ' selected' : '');
    row.style.paddingLeft = 8 + depth * 14 + 'px';

    const chev = node.type === 'folder'
      ? `<span class="chev">▶</span>`
      : `<span class="chev"></span>`;
    const ic = node.type === 'folder'
      ? `<span class="folder-ic">${FOLDER_SVG}</span>`
      : iconFor(node.name);

    row.innerHTML = `${chev}${ic}<span class="tname"></span>
      <span class="tactions">
        <button title="Rename" data-act="rename">✏️</button>
        <button title="Delete" data-act="del">🗑️</button>
      </span>`;
    row.querySelector('.tname').textContent = node.name;

    row.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (btn) {
        e.stopPropagation();
        if (btn.dataset.act === 'del') remove(node);
        else if (btn.dataset.act === 'rename') rename(node);
        return;
      }
      selectedId = node.id;
      if (node.type === 'folder') {
        openSet.has(node.id) ? openSet.delete(node.id) : openSet.add(node.id);
      }
      renderTree();
      if (node.type === 'file' && window.Files.onOpen) window.Files.onOpen(node);
      if (window.Files.onSelect) window.Files.onSelect(node);
      // auto-close explorer on phones
      if (window.matchMedia('(max-width: 820px)').matches && node.type === 'file') {
        if (window.Files.onMobileOpen) window.Files.onMobileOpen();
      }
    });

    container.appendChild(row);

    if (node.type === 'folder') {
      const kids = document.createElement('div');
      kids.className = 'tree-children' + (openSet.has(node.id) ? ' open' : '');
      node.children.forEach((c) => renderNode(c, depth + 1, kids));
      container.appendChild(kids);
    }
  }

  // ---------- import ----------
  async function importFiles(fileList) {
    const files = Array.from(fileList);
    if (!files.length) return;
    for (const f of files) {
      const rel = f.webkitRelativePath && f.webkitRelativePath.includes('/')
        ? f.webkitRelativePath.split('/').slice(1).join('/') // drop top folder name
        : f.name;
      const parts = rel.split('/').filter(Boolean);
      let parent = root;
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const last = i === parts.length - 1;
        if (last) {
          let node = parent.children.find((c) => c.name === part);
          try {
            const text = await f.text();
            if (node && node.type === 'file') node.content = text;
            else {
              node = makeNode(part, 'file', text);
              parent.children.push(node);
            }
          } catch (e) {
            console.warn('cannot read', part, e);
          }
        } else {
          let dir = parent.children.find((c) => c.type === 'folder' && c.name === part);
          if (!dir) {
            dir = makeNode(part, 'folder');
            parent.children.push(dir);
          }
          openSet.add(dir.id);
          parent = dir;
        }
      }
    }
    save();
    indexNodes();
    renderTree();
    if (window.Files.onImported) window.Files.onImported(files.length);
  }

  // ---------- export ----------
  function download(filename, blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  async function exportZip() {
    if (typeof JSZip === 'undefined') { alert('Export library still loading, try again in a moment.'); return; }
    const zip = new JSZip();
    let count = 0;
    (function walk(n, folder) {
      n.children.forEach((c) => {
        if (c.type === 'folder') {
          walk(c, folder.folder(c.name));
        } else {
          folder.file(c.name, c.content || '');
          count++;
        }
      });
    })(root, zip);
    if (!count) { alert('Nothing to export — create some files first.'); return; }
    const blob = await zip.generateAsync({ type: 'blob' });
    download('pyide-project.zip', blob);
  }

  function exportFile(node) {
    if (!node || node.type !== 'file') { alert('Open a file first, then export it.'); return; }
    download(node.name, new Blob([node.content || ''], { type: 'text/plain' }));
  }

  // ---------- public API ----------
  window.Files = {
    iconFor,
    init(container, defaultTree) {
      treeEl = container;
      load(defaultTree);
      renderTree();
    },
    get root() { return root; },
    get selected() { return nodeById.get(selectedId) || null; },
    pathOf,
    findByPath,
    getNode(id) { return nodeById.get(id); },
    allFiles() {
      const out = [];
      (function walk(n) {
        n.children.forEach((c) => c.type === 'folder' ? walk(c) : out.push(c));
      })(root);
      return out;
    },
    newFile() { createEntry('file'); },
    newFolder() { createEntry('folder'); },
    remove, rename,
    renderTree,
    save,
    refreshIds: indexNodes,
    importFiles,
    exportZip,
    exportFile,
    download,
    makeNode,
    // hooks
    onOpen: null, onSelect: null, onDeleted: null, onRenamed: null,
    onImported: null, onMobileOpen: null,
  };
})();
