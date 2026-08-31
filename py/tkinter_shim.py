# ============================================================
# tkinter_shim.py — a DOM-backed Tkinter implementation for the
# browser. Runs inside Pyodide; widgets become real HTML elements
# rendered into the "GUI Preview" panel.
# ============================================================
import sys, types, re

from js import document, window

DESKTOP_ID = "tk-desktop"

_windows = []
_default_root = None


def _desktop():
    d = document.getElementById(DESKTOP_ID)
    if d is None:
        d = document.createElement("div")
        d.id = DESKTOP_ID
    return d


def _show_gui():
    try:
        f = window.globalThis.__tkShow
        if f is not None:
            f()
    except Exception:
        pass


def _el(tag, class_name=None):
    e = document.createElement(tag)
    if class_name:
        e.className = class_name
    return e


# ----------------------------------------------------------------
# Event handling
# ----------------------------------------------------------------
def _keysym(k):
    m = {
        "Enter": "Return", " ": "space", "Escape": "Escape", "Tab": "Tab",
        "Backspace": "BackSpace", "Delete": "Delete", "Home": "Home", "End": "End",
        "ArrowUp": "Up", "ArrowDown": "Down", "ArrowLeft": "Left", "ArrowRight": "Right",
    }
    return m.get(k, k)


class Event(object):
    def __init__(self, widget, e):
        self.widget = widget
        self.x = int(getattr(e, "offsetX", 0) or 0)
        self.y = int(getattr(e, "offsetY", 0) or 0)
        self.x_root = int(getattr(e, "clientX", 0) or 0)
        self.y_root = int(getattr(e, "clientY", 0) or 0)
        k = getattr(e, "key", "") or ""
        self.char = k if len(k) == 1 else ""
        self.keysym = _keysym(k)
        self.keycode = int(getattr(e, "keyCode", 0) or 0)
        self.num = 1
        self.state = 0
        self.type = "event"
        self.delta = int(getattr(e, "deltaY", 0) or 0)


def _key_is(key):
    return lambda e: getattr(e, "key", "") == key


EVENT_MAP = {
    "<Button-1>": ("click", None), "<ButtonPress-1>": ("click", None), "<1>": ("click", None),
    "<Button-2>": ("auxclick", None), "<Button-3>": ("contextmenu", None),
    "<ButtonRelease-1>": ("mouseup", None),
    "<Double-Button-1>": ("dblclick", None),
    "<Motion>": ("mousemove", None), "<B1-Motion>": ("mousemove", None),
    "<Enter>": ("mouseover", None), "<Leave>": ("mouseout", None),
    "<MouseWheel>": ("wheel", None),
    "<FocusIn>": ("focus", None), "<FocusOut>": ("blur", None),
    "<Key>": ("keydown", None), "<KeyPress>": ("keydown", None), "<KeyRelease>": ("keyup", None),
    "<Return>": ("keydown", _key_is("Enter")),
    "<KP_Enter>": ("keydown", _key_is("Enter")),
    "<Escape>": ("keydown", _key_is("Escape")),
    "<BackSpace>": ("keydown", _key_is("Backspace")),
    "<Tab>": ("keydown", _key_is("Tab")),
    "<space>": ("keydown", _key_is(" ")),
    "<Up>": ("keydown", _key_is("ArrowUp")),
    "<Down>": ("keydown", _key_is("ArrowDown")),
    "<Left>": ("keydown", _key_is("ArrowLeft")),
    "<Right>": ("keydown", _key_is("ArrowRight")),
    "<<ComboboxSelected>>": ("change", None),
    "<<ListboxSelect>>": ("change", None),
    "<Configure>": None,
}


class TclError(Exception):
    pass


# ----------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------
def _font_parts(font):
    size, weight, family = None, "normal", None
    if font is None:
        return family, size, weight
    if isinstance(font, (tuple, list)):
        for part in font:
            if isinstance(part, int):
                size = part
            elif isinstance(part, str):
                low = part.lower()
                if low in ("bold", "heavy"):
                    weight = "bold"
                elif low in ("italic", "oblique"):
                    pass
                else:
                    family = part
    else:
        family = getattr(font, "_family", None)
        size = getattr(font, "_size", None)
        weight = getattr(font, "_weight", "normal")
    return family, size, weight


def _apply_font(el, font):
    family, size, weight = _font_parts(font)
    if size:
        el.style.fontSize = str(size) + "px"
    if weight:
        el.style.fontWeight = weight
    if family:
        el.style.fontFamily = family


# ----------------------------------------------------------------
# Base widget
# ----------------------------------------------------------------
class BaseWidget(object):
    # Subclasses that replace self.el with their own DOM element after
    # construction set this True so the default <div> is never attached.
    _own_element = False

    def __init__(self, master=None, cnf=None, **kw):
        self.master = master if master is not None else _default_root
        self.children = []
        self._bindings = []
        self.el = _el("div")
        self._body = self.el
        self.tk = _DummyTk()
        d = dict(cnf or {})
        d.update(kw)
        if (not self._own_element
                and self.master is not None and hasattr(self.master, "_add_child")):
            self.master._add_child(self)
        try:
            self.config(**d)
        except Exception:
            pass

    def _add_child(self, w):
        self.children.append(w)
        (self._body or self.el).appendChild(w.el)

    # ---- options ----
    def config(self, cnf=None, **kw):
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass
    configure = config

    def cget(self, key):
        return getattr(self, "_opt_" + str(key), None)

    def __getitem__(self, key):
        return self.cget(key)

    def __setitem__(self, key, value):
        self._set_opt(key, value)

    def _set_opt(self, k, v):
        setattr(self, "_opt_" + k, v)
        handler = getattr(self, "_opt_set_" + k, None)
        if handler is not None:
            handler(v)

    def _opt_set_bg(self, v):
        self.el.style.background = v
    _opt_set_background = _opt_set_bg

    def _opt_set_fg(self, v):
        self.el.style.color = v
    _opt_set_foreground = _opt_set_fg

    def _opt_set_font(self, v):
        _apply_font(self.el, v)

    def _opt_set_relief(self, v):
        m = {"groove": "groove", "ridge": "ridge", "sunken": "inset",
             "raised": "outset", "solid": "solid", "flat": "none"}
        self.el.style.borderStyle = m.get(str(v), "")

    def _opt_set_cursor(self, v):
        try:
            self.el.style.cursor = v
        except Exception:
            pass

    # ---- events ----
    def bind(self, sequence=None, func=None, add=None):
        if sequence is None:
            return ""
        spec = EVENT_MAP.get(sequence)
        if spec is None:
            return ""
        dom, flt = spec
        if dom is None:
            return ""

        def wrapper(e):
            try:
                if flt is not None and not flt(e):
                    return
                func(Event(self, e))
            except Exception as ex:
                window.console.error("tk bind error: " + str(ex))

        self.el.addEventListener(dom, wrapper)
        self._bindings.append((dom, wrapper))
        return "bind" + str(len(self._bindings))

    def unbind(self, sequence=None, funcid=None):
        spec = EVENT_MAP.get(sequence)
        if spec is None:
            return
        dom = spec[0]
        kept = []
        for d, w in self._bindings:
            if d == dom:
                try:
                    self.el.removeEventListener(d, w)
                except Exception:
                    pass
            else:
                kept.append((d, w))
        self._bindings = kept

    def bind_all(self, seq=None, func=None, add=None):
        return self.bind(seq, func)

    def bindtags(self, tags=None):
        return ()

    def event_generate(self, sequence=None, **kw):
        pass

    # ---- timers ----
    def after(self, ms, func=None, *args):
        if func is None:
            return None

        def run():
            try:
                func(*args)
            except Exception as ex:
                window.console.error("after error: " + str(ex))

        return window.setTimeout(run, int(ms))

    def after_cancel(self, id):
        try:
            window.clearTimeout(id)
        except Exception:
            pass

    after_idle = after

    # ---- lifecycle ----
    def destroy(self):
        for c in list(self.children):
            try:
                c.destroy()
            except Exception:
                pass
        try:
            self.el.remove()
        except Exception:
            pass
        if self.master is not None:
            try:
                self.master.children.remove(self)
            except Exception:
                pass

    def winfo_exists(self):
        return 1

    def winfo_width(self):
        return int(self.el.offsetWidth or 0)

    def winfo_height(self):
        return int(self.el.offsetHeight or 0)

    def winfo_x(self):
        return int(getattr(self.el, "offsetLeft", 0) or 0)

    def winfo_y(self):
        return int(getattr(self.el, "offsetTop", 0) or 0)

    def winfo_class(self):
        return type(self).__name__

    def winfo_children(self):
        return list(self.children)

    def winfo_toplevel(self):
        w = self
        while w.master is not None:
            w = w.master
        return w

    def focus_set(self):
        try:
            self.el.focus()
        except Exception:
            pass
    focus = focus_set

    def grab_set(self):
        pass
    grab_release = grab_set

    def lift(self, aboveThis=None):
        try:
            self.el.style.zIndex = str(999 + len(_windows))
        except Exception:
            pass

    def tkraise(self, aboveThis=None):
        self.lift(aboveThis)

    def lower(self, belowThis=None):
        try:
            self.el.style.zIndex = "1"
        except Exception:
            pass

    def update(self):
        pass
    update_idletasks = update

    def wait_window(self, window=None):
        pass
    wait_visibility = wait_window

    def clipboard_clear(self):
        window.__tk_clip = ""

    def clipboard_append(self, s):
        window.__tk_clip = str(s)

    def clipboard_get(self):
        return str(getattr(window, "__tk_clip", "") or "")

    def nametowidget(self, name):
        return self

    def option_add(self, *args, **kw):
        pass

    def __str__(self):
        return "." + type(self).__name__.lower()

    # ---- layout: pack ----
    def pack(self, cnf=None, **kw):
        d = dict(cnf or {})
        d.update(kw)
        parent = self.master
        body = parent._body if parent is not None else self.el
        body.className = (body.className or "").replace("tk-grid", "").strip()
        body.classList.add("tk-pack")
        side = str(d.get("side", "top"))
        body.style.flexDirection = "column" if side in ("top", "bottom") else "row"
        if side == "bottom":
            self.el.style.order = "99"
        elif side == "right":
            self.el.style.order = "98"
        fill = str(d.get("fill", "") or "")
        expand = d.get("expand", False)
        if str(expand) in ("1", "True", "true") or expand is True:
            self.el.style.flex = "1 1 auto"
        if fill in ("x", "both"):
            self.el.style.width = "100%"
            self.el.style.alignSelf = "stretch"
        if fill in ("y", "both"):
            self.el.style.height = "100%"
            self.el.style.alignSelf = "stretch"
        padx = int(d.get("padx", 0) or 0)
        pady = int(d.get("pady", 0) or 0)
        if padx or pady:
            self.el.style.margin = str(pady) + "px " + str(padx) + "px"
        ipx = int(d.get("ipadx", 0) or 0)
        ipy = int(d.get("ipady", 0) or 0)
        if ipx or ipy:
            self.el.style.padding = str(ipy) + "px " + str(ipx) + "px"
        anchor = d.get("anchor")
        if anchor:
            a = str(anchor)
            if "w" in a:
                self.el.style.alignSelf = "flex-start"
            elif "e" in a:
                self.el.style.alignSelf = "flex-end"

    pack_propagate = lambda self, *a, **k: 1

    def pack_forget(self):
        self.el.style.display = "none"

    def pack_info(self):
        return {}

    # ---- layout: grid ----
    def grid(self, cnf=None, **kw):
        d = dict(cnf or {})
        d.update(kw)
        parent = self.master
        body = parent._body if parent is not None else self.el
        body.classList.add("tk-grid")
        body.classList.remove("tk-pack")
        row = int(d.get("row", 0) or 0)
        col = int(d.get("column", 0) or 0)
        rs = int(d.get("rowspan", 1) or 1)
        cs = int(d.get("columnspan", 1) or 1)
        self.el.style.gridRow = str(row + 1) + " / span " + str(rs)
        self.el.style.gridColumn = str(col + 1) + " / span " + str(cs)
        sticky = str(d.get("sticky", "") or "")
        if sticky:
            if "w" in sticky:
                self.el.style.justifySelf = "start"
            elif "e" in sticky:
                self.el.style.justifySelf = "end"
            else:
                self.el.style.justifySelf = "stretch"
            if "n" in sticky:
                self.el.style.alignSelf = "start"
            elif "s" in sticky:
                self.el.style.alignSelf = "end"
            else:
                self.el.style.alignSelf = "stretch"
        padx = int(d.get("padx", 0) or 0)
        pady = int(d.get("pady", 0) or 0)
        if padx or pady:
            self.el.style.margin = str(pady) + "px " + str(padx) + "px"
        ipx = int(d.get("ipadx", 0) or 0)
        ipy = int(d.get("ipady", 0) or 0)
        if ipx or ipy:
            self.el.style.padding = str(ipy) + "px " + str(ipx) + "px"

    grid_propagate = lambda self, *a, **k: 1

    def grid_forget(self):
        self.el.style.display = "none"

    def grid_info(self):
        return {}

    def grid_rowconfigure(self, index, cnf=None, **kw):
        pass
    grid_columnconfigure = grid_rowconfigure

    # ---- layout: place ----
    def place(self, cnf=None, **kw):
        d = dict(cnf or {})
        d.update(kw)
        self.el.style.position = "absolute"
        if "x" in d:
            self.el.style.left = str(int(d["x"])) + "px"
        if "y" in d:
            self.el.style.top = str(int(d["y"])) + "px"
        if "relx" in d:
            self.el.style.left = str(float(d["relx"]) * 100) + "%"
        if "rely" in d:
            self.el.style.top = str(float(d["rely"]) * 100) + "%"
        if "width" in d:
            self.el.style.width = str(int(d["width"])) + "px"
        if "height" in d:
            self.el.style.height = str(int(d["height"])) + "px"

    def place_forget(self):
        self.el.style.position = ""
        self.el.style.left = self.el.style.top = ""


class _DummyTk(object):
    def call(self, *args):
        return ""

    def eval(self, *args):
        return ""

    def split(self, *args):
        return ()

    def createcommand(self, *a, **k):
        pass

    def deletecommand(self, *a, **k):
        pass


# ----------------------------------------------------------------
# Windows: Tk and Toplevel
# ----------------------------------------------------------------
class _Window(BaseWidget):
    def __init__(self, set_default=True):
        self.master = None
        self.children = []
        self._bindings = []
        self._closed = False
        self._protocol_close = None
        self.tk = _DummyTk()
        self.el = _el("div", "tk-window")

        self._bar = _el("div", "tk-titlebar")
        self._title_lbl = _el("span", "tk-title")
        self._title_lbl.textContent = "tk"
        self._close_btn = _el("button", "tk-close")
        self._close_btn.textContent = "\u2715"
        self._bar.appendChild(self._title_lbl)
        self._bar.appendChild(self._close_btn)

        self._body = _el("div", "tk-body")
        self.el.appendChild(self._bar)
        self.el.appendChild(self._body)

        idx = len(_windows)
        self.el.style.left = str(40 + (idx % 8) * 28) + "px"
        self.el.style.top = str(30 + (idx % 8) * 26) + "px"
        self.el.style.width = "340px"
        self.el.style.zIndex = str(10 + idx)

        _desktop().appendChild(self.el)
        _windows.append(self)
        global _default_root
        if set_default or _default_root is None:
            _default_root = self

        self._close_btn.addEventListener("click", lambda e: self._on_close())
        self._make_draggable()
        _show_gui()

    def _make_draggable(self):
        state = {"on": False, "dx": 0, "dy": 0}

        def down(e):
            state["on"] = True
            state["dx"] = e.clientX - self.el.offsetLeft
            state["dy"] = e.clientY - self.el.offsetTop
            e.preventDefault()

        def move(e):
            if not state["on"]:
                return
            self.el.style.left = str(int(e.clientX - state["dx"])) + "px"
            self.el.style.top = str(int(e.clientY - state["dy"])) + "px"

        def up(e):
            state["on"] = False

        self._bar.addEventListener("pointerdown", down)
        window.addEventListener("pointermove", move)
        window.addEventListener("pointerup", up)

    def _on_close(self):
        if self._protocol_close is not None:
            try:
                self._protocol_close()
            except Exception as ex:
                window.console.error(str(ex))
        else:
            self.destroy()

    # ---- wm methods ----
    def title(self, string=None):
        if string is None:
            return self._title_lbl.textContent
        self._title_lbl.textContent = str(string)
        return None

    def geometry(self, geometry=None):
        if geometry is None:
            return str(self.el.offsetWidth) + "x" + str(self.el.offsetHeight)
        m = re.match(r"\s*(?:(\d+)x(\d+))?\s*([+-]\d+)?([+-]\d+)?\s*$", str(geometry))
        if not m:
            return None
        w, h, x, y = m.group(1), m.group(2), m.group(3), m.group(4)
        if w:
            self.el.style.width = w + "px"
        if h:
            self.el.style.height = h + "px"
        desk = _desktop()
        if x is not None:
            xv = int(x)
            if xv < 0 and w:
                xv = max(0, int(desk.clientWidth or 800) - int(w) + xv)
            self.el.style.left = str(xv) + "px"
        if y is not None:
            yv = int(y)
            if yv < 0 and h:
                yv = max(0, int(desk.clientHeight or 600) - int(h) + yv)
            self.el.style.top = str(yv) + "px"
        return None

    def resizable(self, width=None, height=None):
        pass

    def minsize(self, width=None, height=None):
        if width:
            self.el.style.minWidth = str(width) + "px"
        if height:
            self.el.style.minHeight = str(height) + "px"

    def maxsize(self, width=None, height=None):
        if width:
            self.el.style.maxWidth = str(width) + "px"
        if height:
            self.el.style.maxHeight = str(height) + "px"

    def configure(self, cnf=None, **kw):
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                if k in ("bg", "background"):
                    self._body.style.background = str(v)
                elif k in ("width",):
                    self.el.style.width = str(int(v)) + "px"
                elif k in ("height",):
                    self.el.style.height = str(int(v)) + "px"
                elif k == "menu":
                    pass
                elif k == "cursor":
                    self.el.style.cursor = str(v)
                else:
                    self._set_opt(k, v)
            except Exception:
                pass
    config = configure

    def iconbitmap(self, bitmap=None, default=None):
        pass
    iconphoto = iconbitmap
    wm_iconbitmap = iconbitmap

    def protocol(self, name=None, func=None):
        if name == "WM_DELETE_WINDOW":
            self._protocol_close = func

    def withdraw(self):
        self.el.style.display = "none"

    def deiconify(self):
        self.el.style.display = "flex"
    iconify = withdraw
    wm_deiconify = deiconify
    wm_withdraw = withdraw

    def overrideredirect(self, boolean=None):
        self._bar.style.display = "none" if boolean else "flex"

    def state(self, newstate=None):
        if newstate == "withdrawn":
            self.withdraw()
        elif newstate in ("normal", "zoomed"):
            self.deiconify()
        return "normal"

    def mainloop(self, n=0):
        pass

    def quit(self):
        pass

    def winfo_screenwidth(self):
        return int(window.innerWidth or 800)

    def winfo_screenheight(self):
        return int(window.innerHeight or 600)

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        BaseWidget.destroy(self)
        try:
            _windows.remove(self)
        except Exception:
            pass
        global _default_root
        if _default_root is self:
            _default_root = _windows[-1] if _windows else None


class Tk(_Window):
    def __init__(self, screenName=None, baseName=None, className="Tk",
                 useTk=True, sync=False, use=None):
        _Window.__init__(self, set_default=True)
        self._title_lbl.textContent = className or "Tk"


class Toplevel(_Window):
    def __init__(self, master=None, cnf=None, **kw):
        _Window.__init__(self, set_default=False)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass


# ----------------------------------------------------------------
# Containers
# ----------------------------------------------------------------
class Frame(BaseWidget):
    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el.className = "tk-frame"
        if not getattr(self, "_opt_bg", None) and not getattr(self, "_opt_background", None):
            self.el.style.background = "transparent"

    def _opt_set_bg(self, v):
        self.el.style.background = v
    _opt_set_background = _opt_set_bg

    def _opt_set_borderwidth(self, v):
        self.el.style.borderWidth = str(int(v or 0)) + "px"
        self.el.style.borderStyle = "solid"
        self.el.style.borderColor = "#a7a7a7"
    _opt_set_bd = _opt_set_borderwidth


class LabelFrame(BaseWidget):
    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el.className = "tk-labelframe"
        self._label = _el("span", "tk-lf-label")
        self.el.appendChild(self._label)

    def _opt_set_text(self, v):
        self._label.textContent = str(v)

    def _opt_set_bg(self, v):
        self.el.style.background = v
        self._label.style.background = v
    _opt_set_background = _opt_set_bg

    def _opt_set_labelanchor(self, v):
        pass


# ----------------------------------------------------------------
# Simple widgets
# ----------------------------------------------------------------
class Label(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("span", "tk-label")
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        self.el.style.display = "inline-block"
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _opt_set_text(self, v):
        self.el.textContent = "" if v is None else str(v)

    def _opt_set_wraplength(self, v):
        self.el.style.maxWidth = str(int(v or 0)) + "px"
        self.el.style.whiteSpace = "normal"

    def _opt_set_justify(self, v):
        self.el.style.textAlign = str(v)

    def _opt_set_anchor(self, v):
        a = str(v)
        self.el.style.textAlign = "left" if "w" in a else ("right" if "e" in a else "center")

    def _opt_set_image(self, v):
        pass
    _opt_set_bitmap = _opt_set_image

    def _opt_set_padx(self, v):
        self.el.style.paddingLeft = str(int(v or 0)) + "px"
        self.el.style.paddingRight = str(int(v or 0)) + "px"

    def _opt_set_pady(self, v):
        self.el.style.paddingTop = str(int(v or 0)) + "px"
        self.el.style.paddingBottom = str(int(v or 0)) + "px"


class Button(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("button", "tk-btn")
        self._cmd = None
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        self.el.addEventListener("click", self._fire)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _fire(self, e=None):
        if self._cmd is not None:
            try:
                self._cmd()
            except Exception as ex:
                window.console.error("button command error: " + str(ex))

    def _opt_set_text(self, v):
        self.el.textContent = "" if v is None else str(v)

    def _opt_set_command(self, v):
        self._cmd = v

    def _opt_set_state(self, v):
        self.el.disabled = str(v) == "disabled"

    def _opt_set_width(self, v):
        try:
            self.el.style.minWidth = str(int(v) * 9 + 16) + "px"
        except Exception:
            pass

    def _opt_set_image(self, v):
        pass

    def invoke(self):
        self._fire()


class Entry(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("input", "tk-entry")
        self.el.type = "text"
        self._var = None
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass

        def on_input(e):
            if self._var is not None:
                try:
                    self._var.set(self.el.value)
                except Exception:
                    pass

        self.el.addEventListener("input", on_input)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def get(self):
        return str(self.el.value or "")

    def _idx(self, index):
        val = str(self.el.value or "")
        if index == "end":
            return len(val)
        if index == "insert":
            return int(self.el.selectionStart or 0)
        try:
            return max(0, min(int(index), len(val)))
        except Exception:
            return len(val)

    def insert(self, index, s):
        val = str(self.el.value or "")
        pos = self._idx(index)
        self.el.value = val[:pos] + str(s) + val[pos:]
        if self._var is not None:
            try:
                self._var.set(self.el.value)
            except Exception:
                pass

    def delete(self, first, last=None):
        val = str(self.el.value or "")
        a = self._idx(first)
        b = self._idx(last) if last is not None else a + 1
        self.el.value = val[:a] + val[b:]

    def icursor(self, index):
        try:
            p = self._idx(index)
            self.el.setSelectionRange(p, p)
        except Exception:
            pass

    def select_range(self, start, end):
        try:
            self.el.setSelectionRange(self._idx(start), self._idx(end))
        except Exception:
            pass

    def select_clear(self):
        try:
            self.el.setSelectionRange(0, 0)
        except Exception:
            pass

    def _opt_set_show(self, v):
        self.el.type = "password" if v else "text"

    def _opt_set_textvariable(self, v):
        self._var = v
        if v is not None:
            try:
                self.el.value = str(v.get())
                v.trace_add("write", lambda *a: self._sync_from_var())
            except Exception:
                pass

    def _sync_from_var(self):
        try:
            val = str(self._var.get())
            if self.el.value != val:
                self.el.value = val
        except Exception:
            pass

    def _opt_set_state(self, v):
        self.el.disabled = str(v) == "disabled"
        if str(v) == "readonly":
            self.el.readOnly = True

    def _opt_set_width(self, v):
        try:
            self.el.style.width = str(max(60, int(v) * 9)) + "px"
        except Exception:
            pass


class Text(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("textarea", "tk-text")
        self.el.spellcheck = False
        self.marks = {}
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _tidx(self, index):
        val = str(self.el.value or "")
        if index == "end":
            return len(val)
        if index == "insert":
            return int(self.el.selectionStart or 0)
        if isinstance(index, (int, float)):
            return min(int(index), len(val))
        s = str(index)
        if "." in s:
            parts = s.split(".", 1)
            try:
                ln = int(parts[0]) - 1
                col = int(parts[1].split()[0])
            except Exception:
                return len(val)
            lines = val.split("\n")
            off = 0
            for i in range(max(0, min(ln, len(lines)))):
                off += len(lines[i]) + 1
            return min(off + col, len(val))
        try:
            return min(int(s), len(val))
        except Exception:
            return len(val)

    def get(self, index1, index2=None):
        val = str(self.el.value or "")
        a = self._tidx(index1)
        if index2 is None:
            return val[a:a + 1]
        b = self._tidx(index2)
        return val[a:b]

    def insert(self, index, s, *tags):
        val = str(self.el.value or "")
        p = self._tidx(index)
        self.el.value = val[:p] + str(s) + val[p:]

    def delete(self, index1, index2=None):
        val = str(self.el.value or "")
        a = self._tidx(index1)
        b = self._tidx(index2) if index2 is not None else a + 1
        self.el.value = val[:a] + val[b:]

    def see(self, index):
        pass

    def index(self, index):
        p = self._tidx(index)
        before = str(self.el.value or "")[:p]
        ln = before.count("\n") + 1
        col = p - (before.rfind("\n") + 1)
        return str(ln) + "." + str(col)

    def mark_set(self, mark, index):
        self.marks[mark] = self._tidx(index)

    def mark_gravity(self, mark, direction=None):
        return "right"

    def tag_config(self, tagName, cnf=None, **kw):
        pass
    tag_configure = tag_config

    def tag_add(self, tagName, index1, index2=None):
        pass

    def tag_remove(self, tagName, index1, index2=None):
        pass

    def tag_bind(self, tagName, sequence, func):
        return self.bind(sequence, func)

    def search(self, pattern, index, *args, **kw):
        return ""

    def _opt_set_width(self, v):
        try:
            self.el.style.width = str(max(120, int(v) * 9)) + "px"
        except Exception:
            pass

    def _opt_set_height(self, v):
        try:
            self.el.rows = max(3, int(v))
        except Exception:
            pass

    def _opt_set_wrap(self, v):
        self.el.style.whiteSpace = "pre-wrap" if str(v) in ("word", "char") else "pre"

    def _opt_set_state(self, v):
        self.el.disabled = str(v) == "disabled"

    def _opt_set_textvariable(self, v):
        pass


# ----------------------------------------------------------------
# Buttons with variables
# ----------------------------------------------------------------
_radio_counter = [0]


class Checkbutton(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("label", "tk-check")
        self._input = _el("input")
        self._input.type = "checkbox"
        self._lbl = _el("span")
        self.el.appendChild(self._input)
        self.el.appendChild(self._lbl)
        self._var = None
        self._on = 1
        self._off = 0
        self._cmd = None
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        self._input.addEventListener("change", self._changed)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _changed(self, e=None):
        if self._var is not None:
            try:
                self._var.set(self._on if self._input.checked else self._off)
            except Exception:
                pass
        if self._cmd is not None:
            try:
                self._cmd()
            except Exception as ex:
                window.console.error(str(ex))

    def _opt_set_text(self, v):
        self._lbl.textContent = "" if v is None else str(v)

    def _opt_set_command(self, v):
        self._cmd = v

    def _opt_set_variable(self, v):
        self._var = v
        if v is not None:
            try:
                self._input.checked = (v.get() == self._on)
            except Exception:
                pass

    def _opt_set_onvalue(self, v):
        self._on = v

    def _opt_set_offvalue(self, v):
        self._off = v

    def _opt_set_state(self, v):
        self._input.disabled = str(v) == "disabled"

    def invoke(self):
        self._input.checked = not self._input.checked
        self._changed()


class Radiobutton(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("label", "tk-radio")
        self._input = _el("input")
        self._input.type = "radio"
        _radio_counter[0] += 1
        self._group = "tkr" + str(_radio_counter[0])
        self._input.name = self._group
        self._lbl = _el("span")
        self.el.appendChild(self._input)
        self.el.appendChild(self._lbl)
        self._var = None
        self._value = None
        self._cmd = None
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        self._input.addEventListener("change", self._changed)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _changed(self, e=None):
        if self._var is not None:
            try:
                self._var.set(self._value)
            except Exception:
                pass
        if self._cmd is not None:
            try:
                self._cmd()
            except Exception:
                pass

    def _opt_set_text(self, v):
        self._lbl.textContent = "" if v is None else str(v)

    def _opt_set_command(self, v):
        self._cmd = v

    def _opt_set_variable(self, v):
        self._var = v
        if v is not None:
            try:
                self._input.name = "var" + str(id(v))
                self._input.checked = (str(v.get()) == str(self._value))
            except Exception:
                pass

    def _opt_set_value(self, v):
        self._value = v
        self._input.value = str(v)
        if self._var is not None:
            try:
                self._input.checked = (str(self._var.get()) == str(v))
            except Exception:
                pass

    def _opt_set_state(self, v):
        self._input.disabled = str(v) == "disabled"

    def invoke(self):
        self._input.checked = True
        self._changed()


class Scale(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("input", "tk-scale")
        self.el.type = "range"
        self.el.min = "0"
        self.el.max = "100"
        self.el.step = "1"
        self._cmd = None
        self._var = None
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        self.el.addEventListener("input", self._changed)
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _changed(self, e=None):
        val = self.el.value
        if self._var is not None:
            try:
                self._var.set(val)
            except Exception:
                pass
        if self._cmd is not None:
            try:
                self._cmd(val)
            except Exception as ex:
                window.console.error(str(ex))

    def get(self):
        try:
            return float(self.el.value)
        except Exception:
            return 0.0

    def set(self, value):
        self.el.value = str(value)

    def _opt_set_from_(self, v):
        self.el.min = str(v)
    _opt_set_from = _opt_set_from_

    def _opt_set_to(self, v):
        self.el.max = str(v)

    def _opt_set_resolution(self, v):
        self.el.step = str(v)

    def _opt_set_orient(self, v):
        pass

    def _opt_set_command(self, v):
        self._cmd = v

    def _opt_set_variable(self, v):
        self._var = v

    def _opt_set_label(self, v):
        pass


class Spinbox(Entry):
    def __init__(self, master=None, cnf=None, **kw):
        Entry.__init__(self, master, cnf, **kw)
        try:
            self.el.type = "number"
        except Exception:
            pass

    def _opt_set_from_(self, v):
        self.el.min = str(v)
    _opt_set_from = _opt_set_from_

    def _opt_set_to(self, v):
        self.el.max = str(v)

    def _opt_set_increment(self, v):
        self.el.step = str(v)

    def _opt_set_values(self, v):
        pass


# ----------------------------------------------------------------
# Listbox
# ----------------------------------------------------------------
class Listbox(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = _el("div", "tk-list")
        self._items = []
        self._sel = set()
        self._selmode = "browse"
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def insert(self, index, *elements):
        items = [str(x) for x in elements]
        if index == "end" or index == END:
            self._items.extend(items)
        else:
            try:
                pos = int(index)
                for j, it in enumerate(items):
                    self._items.insert(pos + j, it)
            except Exception:
                self._items.extend(items)
        self._render()

    def delete(self, first, last=None):
        try:
            a = int(first)
            b = int(last) if last is not None else a
            del self._items[a:b + 1]
            self._sel = set()
            self._render()
        except Exception:
            pass

    def get(self, first, last=None):
        try:
            a = int(first)
            if last is None:
                return self._items[a] if 0 <= a < len(self._items) else ""
            b = int(last)
            return tuple(self._items[a:b + 1])
        except Exception:
            return ""

    def size(self):
        return len(self._items)

    def curselection(self):
        return tuple(sorted(self._sel))

    def selection_clear(self, first=None, last=None):
        self._sel = set()
        self._render()

    def selection_set(self, first, last=None):
        try:
            a = int(first)
            b = int(last) if last is not None else a
            for i in range(a, b + 1):
                self._sel.add(i)
            self._render()
        except Exception:
            pass

    def select_set(self, first, last=None):
        self.selection_set(first, last)

    def activate(self, index):
        pass

    def see(self, index):
        pass

    def _render(self):
        self.el.innerHTML = ""
        for i, text in enumerate(self._items):
            row = _el("div", "tk-list-item" + (" sel" if i in self._sel else ""))
            row.textContent = text

            def make_handler(idx):
                def handler(e):
                    if self._selmode in ("multiple", "extended"):
                        if idx in self._sel:
                            self._sel.discard(idx)
                        else:
                            self._sel.add(idx)
                    else:
                        self._sel = {idx}
                    self._render()
                return handler

            row.addEventListener("click", make_handler(i))
            self.el.appendChild(row)

    def _opt_set_selectmode(self, v):
        self._selmode = str(v)

    def _opt_set_height(self, v):
        try:
            self.el.style.maxHeight = str(max(3, int(v)) * 24 + 4) + "px"
        except Exception:
            pass

    def _opt_set_listvariable(self, v):
        pass


# ----------------------------------------------------------------
# Canvas
# ----------------------------------------------------------------
class Canvas(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el = document.createElement("canvas")
        self._items = {}
        self._next = 1
        self.el.style.background = "#f5f5f5"
        self.el.width = 300
        self.el.height = 200
        if self.master is not None and hasattr(self.master, "_body"):
            try:
                self.master._body.appendChild(self.el)
            except Exception:
                pass
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _ctx(self):
        return self.el.getContext("2d")

    def _redraw(self):
        ctx = self._ctx()
        ctx.clearRect(0, 0, self.el.width, self.el.height)
        for iid in sorted(self._items.keys()):
            spec = self._items[iid]
            try:
                self._draw(ctx, spec)
            except Exception as ex:
                window.console.error("canvas draw: " + str(ex))

    def _color(self, v, default):
        if v is None or v == "":
            return default
        return str(v)

    def _draw(self, ctx, spec):
        kind = spec["kind"]
        xy = spec["xy"]
        o = spec["opts"]
        if kind == "line":
            ctx.beginPath()
            ctx.moveTo(xy[0], xy[1])
            for i in range(2, len(xy), 2):
                ctx.lineTo(xy[i], xy[i + 1])
            ctx.strokeStyle = self._color(o.get("fill"), "#000")
            ctx.lineWidth = float(o.get("width", 1) or 1)
            if o.get("dash"):
                ctx.setLineDash([6, 4])
            else:
                ctx.setLineDash([])
            ctx.stroke()
        elif kind == "rectangle":
            x1, y1, x2, y2 = xy
            fill = o.get("fill")
            if fill:
                ctx.fillStyle = str(fill)
                ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
            ctx.strokeStyle = self._color(o.get("outline"), "#000")
            ctx.lineWidth = float(o.get("width", 1) or 1)
            ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
        elif kind == "oval":
            x1, y1, x2, y2 = xy
            ctx.beginPath()
            ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2,
                        abs(x2 - x1) / 2, abs(y2 - y1) / 2, 0, 0, 6.2832)
            fill = o.get("fill")
            if fill:
                ctx.fillStyle = str(fill)
                ctx.fill()
            ctx.strokeStyle = self._color(o.get("outline"), "#000")
            ctx.lineWidth = float(o.get("width", 1) or 1)
            ctx.stroke()
        elif kind == "polygon":
            ctx.beginPath()
            ctx.moveTo(xy[0], xy[1])
            for i in range(2, len(xy), 2):
                ctx.lineTo(xy[i], xy[i + 1])
            ctx.closePath()
            fill = o.get("fill")
            if fill:
                ctx.fillStyle = str(fill)
                ctx.fill()
            ctx.strokeStyle = self._color(o.get("outline"), "#000")
            ctx.lineWidth = float(o.get("width", 1) or 1)
            ctx.stroke()
        elif kind == "arc":
            x1, y1, x2, y2 = xy
            rx = abs(x2 - x1) / 2
            ry = abs(y2 - y1) / 2
            start = float(o.get("start", 0) or 0) * 3.14159 / 180.0
            extent = float(o.get("extent", 90) or 90) * 3.14159 / 180.0
            style = str(o.get("style", "pieslice"))
            ctx.beginPath()
            if style == "pieslice":
                ctx.moveTo((x1 + x2) / 2, (y1 + y2) / 2)
            ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2, rx, ry, 0, start, start + extent)
            if style == "pieslice":
                ctx.closePath()
                fill = o.get("fill")
                if fill:
                    ctx.fillStyle = str(fill)
                    ctx.fill()
            elif style == "chord":
                ctx.closePath()
            ctx.strokeStyle = self._color(o.get("outline"), "#000")
            ctx.lineWidth = float(o.get("width", 1) or 1)
            ctx.stroke()
        elif kind == "text":
            x, y = xy
            anchor = str(o.get("anchor", "center"))
            ctx.fillStyle = self._color(o.get("fill"), "#000")
            font = o.get("font")
            _, size, _w = _font_parts(font)
            ctx.font = str(size or 13) + "px sans-serif"
            if "w" in anchor:
                ctx.textAlign = "left"
            elif "e" in anchor:
                ctx.textAlign = "right"
            else:
                ctx.textAlign = "center"
            ctx.textBaseline = "top" if "n" in anchor else ("bottom" if "s" in anchor else "middle")
            ctx.fillText(str(o.get("text", "")), x, y)

    def _add(self, kind, xy, opts):
        iid = self._next
        self._next += 1
        self._items[iid] = {"kind": kind, "xy": list(xy), "opts": dict(opts)}
        self._redraw()
        return iid

    def create_line(self, *xy, **opts):
        return self._add("line", xy, opts)

    def create_rectangle(self, *xy, **opts):
        return self._add("rectangle", xy, opts)

    def create_oval(self, *xy, **opts):
        return self._add("oval", xy, opts)

    def create_polygon(self, *xy, **opts):
        return self._add("polygon", xy, opts)

    def create_arc(self, *xy, **opts):
        return self._add("arc", xy, opts)

    def create_text(self, x, y, **opts):
        return self._add("text", [x, y], opts)

    def create_window(self, *a, **k):
        return 0

    def create_image(self, *a, **k):
        return 0

    def delete(self, *items):
        for it in items:
            if it == "all" or it == ALL:
                self._items.clear()
            else:
                try:
                    self._items.pop(int(it), None)
                except Exception:
                    pass
        self._redraw()

    def coords(self, item, *xy):
        try:
            spec = self._items.get(int(item))
        except Exception:
            return []
        if spec is None:
            return []
        if xy:
            spec["xy"] = list(xy)
            self._redraw()
        return list(spec["xy"])

    def itemconfig(self, item, cnf=None, **opts):
        d = dict(cnf or {})
        d.update(opts)
        try:
            spec = self._items.get(int(item))
            if spec is not None:
                spec["opts"].update(d)
                self._redraw()
        except Exception:
            pass
    itemconfigure = itemconfig

    def itemcget(self, item, option):
        try:
            return self._items.get(int(item), {}).get("opts", {}).get(option)
        except Exception:
            return None

    def move(self, item, dx, dy):
        try:
            spec = self._items.get(int(item))
            if spec is not None:
                spec["xy"] = [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(spec["xy"])]
                self._redraw()
        except Exception:
            pass

    def tag_bind(self, tagOrId, sequence=None, func=None, add=None):
        return self.bind(sequence, func)

    def canvasx(self, x, gridspacing=None):
        return x

    def canvasy(self, y, gridspacing=None):
        return y

    def _opt_set_width(self, v):
        try:
            self.el.width = int(v)
            self.el.style.width = str(int(v)) + "px"
            self._redraw()
        except Exception:
            pass

    def _opt_set_height(self, v):
        try:
            self.el.height = int(v)
            self.el.style.height = str(int(v)) + "px"
            self._redraw()
        except Exception:
            pass

    def _opt_set_bg(self, v):
        self.el.style.background = str(v)
    _opt_set_background = _opt_set_bg


# ----------------------------------------------------------------
# Menu / images / scrollbar
# ----------------------------------------------------------------
class Menu(object):
    def __init__(self, master=None, cnf=None, **kw):
        self.master = master
        self.tk = _DummyTk()

    def add_command(self, cnf=None, **kw):
        pass

    def add_cascade(self, cnf=None, **kw):
        pass

    def add_separator(self, *a, **k):
        pass

    def add_checkbutton(self, cnf=None, **kw):
        pass

    def add_radiobutton(self, cnf=None, **kw):
        pass

    def entryconfig(self, index, cnf=None, **kw):
        pass
    entryconfigure = entryconfig

    def delete(self, index1, index2=None):
        pass

    def insert(self, index, itemType, cnf=None, **kw):
        pass

    def post(self, x, y):
        pass

    def tk_popup(self, x, y):
        pass

    def tearoff(self, val):
        pass

    def type(self, index):
        return ""

    def invoke(self, index):
        pass


class PhotoImage(object):
    def __init__(self, name=None, cnf=None, master=None, **kw):
        self.tk = _DummyTk()

    def subsample(self, *a, **k):
        return self

    def zoom(self, *a, **k):
        return self

    def copy(self, *a, **k):
        return self

    def configure(self, *a, **k):
        pass
    config = configure

    def cget(self, opt):
        return None

    def width(self):
        return 0

    def height(self):
        return 0

    def get(self, x, y):
        return (0, 0, 0)

    def put(self, data, to=None):
        pass


BitmapImage = PhotoImage


class Scrollbar(BaseWidget):
    _own_element = True

    def __init__(self, master=None, cnf=None, **kw):
        BaseWidget.__init__(self, master, cnf, **kw)
        self.el.className = ""
        self.el.style.background = "#d0d0d0"
        self.el.style.borderRadius = "6px"
        d = dict(cnf or {})
        d.update(kw)
        for k, v in d.items():
            try:
                self._set_opt(k, v)
            except Exception:
                pass

    def _opt_set_orient(self, v):
        if str(v) == "vertical":
            self.el.style.width = "12px"
            self.el.style.alignSelf = "stretch"
        else:
            self.el.style.height = "12px"
            self.el.style.alignSelf = "stretch"

    def set(self, first, last):
        pass

    def get(self):
        return (0.0, 1.0)


# ----------------------------------------------------------------
# Variables
# ----------------------------------------------------------------
class Variable(object):
    _default_value = ""

    def __init__(self, master=None, value=None, name=None):
        self._v = value if value is not None else self._default_value
        self._cbs = []
        self._name = name or ("var" + str(id(self)))

    def set(self, value):
        self._v = value
        for cb in list(self._cbs):
            try:
                cb(self._name, "", "w")
            except Exception:
                pass

    def get(self):
        return self._v

    def trace_add(self, mode, callback):
        self._cbs.append(callback)
        return str(id(callback))

    def trace_variable(self, mode, callback):
        return self.trace_add(mode, callback)

    def trace(self, mode, callback):
        return self.trace_add(mode, callback)

    def trace_remove(self, mode, callback):
        try:
            self._cbs.remove(callback)
        except Exception:
            pass

    def trace_vdelete(self, mode, cbname):
        pass

    def trace_vinfo(self):
        return []


class StringVar(Variable):
    _default_value = ""

    def get(self):
        return "" if self._v is None else str(self._v)


class IntVar(Variable):
    _default_value = 0

    def get(self):
        try:
            return int(float(self._v))
        except Exception:
            return 0


class DoubleVar(Variable):
    _default_value = 0.0

    def get(self):
        try:
            return float(self._v)
        except Exception:
            return 0.0


class BooleanVar(Variable):
    _default_value = False

    def get(self):
        return bool(self._v)

    def set(self, value):
        Variable.set(self, bool(value))


# ----------------------------------------------------------------
# ttk (submodule)
# ----------------------------------------------------------------
def _build_ttk():
    m = types.ModuleType("tkinter.ttk")

    class Style(object):
        def __init__(self, master=None):
            pass

        def configure(self, style, query=None, **kw):
            pass
        config = configure

        def map(self, style, query=None, **kw):
            pass

        def theme_use(self, name=None):
            return "default"

        def theme_names(self):
            return ("default",)

        def layout(self, style, layoutspec=None):
            pass

        def lookup(self, style, option, state=None, default=None):
            return default

        def element_options(self, *a, **k):
            return ()

    class Combobox(BaseWidget):
        _own_element = True

        def __init__(self, master=None, cnf=None, **kw):
            BaseWidget.__init__(self, master, cnf, **kw)
            self.el = _el("input", "tk-entry")
            self.el.type = "text"
            self._list_id = "dl" + str(id(self))
            self._list = _el("datalist")
            self._list.id = self._list_id
            self.el.setAttribute("list", self._list_id)
            self._var = None
            wrap = getattr(self, "_wrap", None)
            if self.master is not None and hasattr(self.master, "_body"):
                try:
                    host = self.master._body
                    host.appendChild(self.el)
                    host.appendChild(self._list)
                except Exception:
                    pass
            self.el.addEventListener("change", lambda e: self._fire())
            d = dict(cnf or {})
            d.update(kw)
            self._cmd = None
            for k, v in d.items():
                try:
                    self._set_opt(k, v)
                except Exception:
                    pass

        def _fire(self):
            if self._var is not None:
                try:
                    self._var.set(self.el.value)
                except Exception:
                    pass

        def get(self):
            return str(self.el.value or "")

        def set(self, value):
            self.el.value = str(value)

        def _opt_set_values(self, v):
            self._list.innerHTML = ""
            for item in (v or ()):
                o = _el("option")
                o.value = str(item)
                self._list.appendChild(o)

        def _opt_set_textvariable(self, v):
            self._var = v
            if v is not None:
                try:
                    self.el.value = str(v.get())
                except Exception:
                    pass

        def _opt_set_state(self, v):
            self.el.disabled = str(v) == "disabled"

        def _opt_set_width(self, v):
            try:
                self.el.style.width = str(max(80, int(v) * 9)) + "px"
            except Exception:
                pass

    class Notebook(BaseWidget):
        _own_element = True

        def __init__(self, master=None, cnf=None, **kw):
            BaseWidget.__init__(self, master, cnf, **kw)
            self.el = _el("div", "tk-nb")
            self._tabsbar = _el("div", "tk-nb-tabs")
            self._body = _el("div", "tk-nb-body")
            self.el.appendChild(self._tabsbar)
            self.el.appendChild(self._body)
            self._pages = []
            if self.master is not None and hasattr(self.master, "_body"):
                try:
                    self.master._body.appendChild(self.el)
                except Exception:
                    pass

        def add(self, child, cnf=None, **kw):
            d = dict(cnf or {})
            d.update(kw)
            page = _el("div", "tk-nb-page")
            page.style.display = "none"
            try:
                page.appendChild(child.el)
            except Exception:
                pass
            self._body.appendChild(page)
            tab = _el("button", "tk-nb-tab")
            tab.textContent = str(d.get("text", "Tab"))
            self._tabsbar.appendChild(tab)
            idx = len(self._pages)
            self._pages.append((tab, page, child))

            def show(e=None):
                self.select(idx)

            tab.addEventListener("click", show)
            if len(self._pages) == 1:
                self.select(0)

        def select(self, tab_id=None):
            if tab_id is None:
                return self._current
            if isinstance(tab_id, BaseWidget):
                for i, (t, p, c) in enumerate(self._pages):
                    if c is tab_id:
                        tab_id = i
                        break
            try:
                idx = int(tab_id)
            except Exception:
                return
            for i, (t, p, c) in enumerate(self._pages):
                p.style.display = "block" if i == idx else "none"
                if i == idx:
                    t.classList.add("active")
                else:
                    t.classList.remove("active")
            self._current = idx

        def tabs(self):
            return tuple(c for _, _, c in self._pages)

        def index(self, tab_id):
            return 0

        def hide(self, tab_id):
            pass

        def enable(self, tab_id):
            pass

    class Progressbar(BaseWidget):
        _own_element = True

        def __init__(self, master=None, cnf=None, **kw):
            BaseWidget.__init__(self, master, cnf, **kw)
            self.el = _el("div", "tk-progress")
            self._fill = _el("div", "tk-progress-fill")
            self._fill.style.width = "0%"
            self.el.appendChild(self._fill)
            self._max = 100.0
            self._value = 0.0
            if self.master is not None and hasattr(self.master, "_body"):
                try:
                    self.master._body.appendChild(self.el)
                except Exception:
                    pass
            d = dict(cnf or {})
            d.update(kw)
            for k, v in d.items():
                try:
                    self._set_opt(k, v)
                except Exception:
                    pass

        def set(self, value):
            self._value = float(value or 0)
            pct = 0 if self._max == 0 else (self._value / self._max * 100.0)
            self._fill.style.width = str(max(0, min(100, pct))) + "%"

        def step(self, amount=1.0):
            self.set(self._value + float(amount))

        def _opt_set_value(self, v):
            self.set(v)

        def _opt_set_maximum(self, v):
            self._max = float(v or 100)

        def _opt_set_orient(self, v):
            if str(v) == "vertical":
                self.el.style.width = "16px"
                self.el.style.height = "120px"

    class Separator(BaseWidget):
        _own_element = True

        def __init__(self, master=None, cnf=None, **kw):
            BaseWidget.__init__(self, master, cnf, **kw)
            self.el = _el("hr", "tk-sep")
            if self.master is not None and hasattr(self.master, "_body"):
                try:
                    self.master._body.appendChild(self.el)
                except Exception:
                    pass
            d = dict(cnf or {})
            d.update(kw)
            for k, v in d.items():
                try:
                    self._set_opt(k, v)
                except Exception:
                    pass

        def _opt_set_orient(self, v):
            if str(v) == "vertical":
                self.el.style.width = "2px"
                self.el.style.height = "100%"
                self.el.style.margin = "0 4px"
            else:
                self.el.style.height = "2px"
                self.el.style.width = "100%"
                self.el.style.margin = "4px 0"

    class Treeview(BaseWidget):
        _own_element = True

        def __init__(self, master=None, cnf=None, **kw):
            BaseWidget.__init__(self, master, cnf, **kw)
            self.el = _el("div", "tk-tree")
            self._cols = ("#0",)
            self._rows = []
            self._head = {}
            if self.master is not None and hasattr(self.master, "_body"):
                try:
                    self.master._body.appendChild(self.el)
                except Exception:
                    pass
            d = dict(cnf or {})
            d.update(kw)
            for k, v in d.items():
                try:
                    self._set_opt(k, v)
                except Exception:
                    pass
            self._render()

        def _opt_set_columns(self, v):
            self._cols = ("#0",) + tuple(v or ())
            self._render()

        def heading(self, column, cnf=None, **kw):
            d = dict(cnf or {})
            d.update(kw)
            if "text" in d:
                self._head[column] = str(d["text"])
                self._render()

        def column(self, column, cnf=None, **kw):
            pass

        def insert(self, parent, index, iid=None, text="", values=(), **kw):
            if iid is None:
                iid = "I" + str(len(self._rows) + 1)
            self._rows.append({"iid": iid, "text": str(text), "values": [str(x) for x in (values or ())]})
            self._render()
            return iid

        def get_children(self, item=""):
            return tuple(r["iid"] for r in self._rows)

        def item(self, iid, option=None, **kw):
            for r in self._rows:
                if r["iid"] == iid:
                    return r.get(option) if option else r
            return None

        def delete(self, *items):
            if not items or items[0] == "all":
                self._rows = []
            else:
                kill = set(items)
                self._rows = [r for r in self._rows if r["iid"] not in kill]
            self._render()

        def selection(self):
            return ()

        def selection_set(self, *items):
            pass

        def _render(self):
            self.el.innerHTML = ""
            head = _el("div", "tk-tree-head")
            for c in self._cols:
                col = _el("span", "tk-tree-col")
                col.textContent = self._head.get(c, c if c != "#0" else "Item")
                head.appendChild(col)
            self.el.appendChild(head)
            for r in self._rows:
                row = _el("div", "tk-tree-row")
                c0 = _el("span", "tk-tree-col")
                c0.textContent = r["text"]
                row.appendChild(c0)
                for v in r["values"]:
                    col = _el("span", "tk-tree-col")
                    col.textContent = v
                    row.appendChild(col)
                self.el.appendChild(row)

    m.Style = Style
    m.Frame = Frame
    m.LabelFrame = LabelFrame
    m.Label = Label
    m.Button = Button
    m.Entry = Entry
    m.Checkbutton = Checkbutton
    m.Radiobutton = Radiobutton
    m.Scale = Scale
    m.Spinbox = Spinbox
    m.Listbox = Listbox
    m.Combobox = Combobox
    m.Notebook = Notebook
    m.Progressbar = Progressbar
    m.Separator = Separator
    m.Treeview = Treeview
    m.Scrollbar = Scrollbar
    m.Widget = BaseWidget
    return m


# ----------------------------------------------------------------
# messagebox / simpledialog / filedialog / font submodules
# ----------------------------------------------------------------
def _msg(title, message):
    t = str(title or "")
    msg = str(message or "")
    if t and t != "tk":
        window.alert(t + "\n" + msg)
    else:
        window.alert(msg)


def _build_messagebox():
    m = types.ModuleType("tkinter.messagebox")

    def showinfo(title=None, message=None, **kw):
        _msg(title, message); return "ok"

    def showwarning(title=None, message=None, **kw):
        _msg(title, message); return "ok"

    def showerror(title=None, message=None, **kw):
        _msg(title, message); return "ok"

    def askyesno(title=None, message=None, **kw):
        return bool(window.confirm((str(title) + "\n" if title else "") + str(message)))

    def askokcancel(title=None, message=None, **kw):
        return bool(window.confirm((str(title) + "\n" if title else "") + str(message)))

    def askyesnocancel(title=None, message=None, **kw):
        ok = window.confirm((str(title) + "\n" if title else "") + str(message) + "\n\n(OK = Yes, Cancel = No)")
        return True if ok else False

    def askquestion(title=None, message=None, **kw):
        return "yes" if window.confirm((str(title) + "\n" if title else "") + str(message)) else "no"

    def askretrycancel(title=None, message=None, **kw):
        return bool(window.confirm((str(title) + "\n" if title else "") + str(message)))

    m.showinfo = showinfo
    m.showwarning = showwarning
    m.showerror = showerror
    m.askyesno = askyesno
    m.askokcancel = askokcancel
    m.askyesnocancel = askyesnocancel
    m.askquestion = askquestion
    m.askretrycancel = askretrycancel
    return m


def _build_simpledialog():
    m = types.ModuleType("tkinter.simpledialog")

    def askstring(title, prompt, **kw):
        r = window.prompt(str(title) + "\n" + str(prompt), str(kw.get("initialvalue", "") or ""))
        return None if r is None else r

    def askinteger(title, prompt, **kw):
        r = window.prompt(str(title) + "\n" + str(prompt), str(kw.get("initialvalue", "0") or "0"))
        if r is None:
            return None
        try:
            return int(r)
        except Exception:
            return None

    def askfloat(title, prompt, **kw):
        r = window.prompt(str(title) + "\n" + str(prompt), str(kw.get("initialvalue", "0") or "0"))
        if r is None:
            return None
        try:
            return float(r)
        except Exception:
            return None

    m.askstring = askstring
    m.askinteger = askinteger
    m.askfloat = askfloat
    return m


def _build_filedialog():
    m = types.ModuleType("tkinter.filedialog")

    def _na(*a, **k):
        window.alert("Native file dialogs are not available in the browser.\nUse the Import / Export buttons in the toolbar instead.")
        return ""

    m.askopenfilename = _na
    m.askopenfilenames = lambda *a, **k: ()
    m.asksaveasfilename = _na
    m.askdirectory = _na
    m.askopenfile = lambda *a, **k: None
    m.asksaveasfile = lambda *a, **k: None
    return m


def _build_font():
    m = types.ModuleType("tkinter.font")

    class Font(object):
        def __init__(self, root=None, font=None, name=None, exists=False, **kw):
            self._family = kw.get("family")
            self._size = kw.get("size", 12)
            self._weight = kw.get("weight", "normal")
            self._slant = kw.get("slant", "roman")
            if isinstance(font, (tuple, list)) and font:
                self._family = font[0]
                if len(font) > 1:
                    self._size = font[1]
                if len(font) > 2:
                    self._weight = "bold" if "bold" in font[2:] else "normal"

        def configure(self, cnf=None, **kw):
            d = dict(cnf or {})
            d.update(kw)
            for k, v in d.items():
                setattr(self, "_" + k, v)
        config = configure

        def cget(self, option):
            return getattr(self, "_" + str(option), None)

        def actual(self, option=None, displayof=None):
            return {"family": self._family or "sans-serif", "size": self._size,
                    "weight": self._weight, "slant": self._slant}

        def measure(self, text, displayof=None):
            return len(str(text)) * 7

        def metrics(self, *a, **k):
            return {"ascent": 11, "descent": 3, "linespace": 16, "fixed": 1}

        def families(self):
            return ("sans-serif", "monospace", "serif")

        def copy(self):
            return Font(family=self._family, size=self._size, weight=self._weight)

    def families(root=None, displayof=None):
        return ("sans-serif", "monospace", "serif")

    def names(root=None):
        return ("TkDefaultFont", "TkTextFont", "TkFixedFont")

    m.Font = Font
    m.families = families
    m.names = names
    m.BOLD = "bold"
    m.ITALIC = "italic"
    m.NORMAL = "normal"
    return m


def _build_colorchooser():
    m = types.ModuleType("tkinter.colorchooser")

    def askcolor(color=None, **kw):
        hx = window.prompt("Choose a color (hex, e.g. #ff0000):", str(color or "#ff0000"))
        if not hx:
            return (None, None)
        try:
            s = str(hx).lstrip("#")
            if len(s) == 3:
                s = "".join(c * 2 for c in s)
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            return ((r, g, b), "#" + s)
        except Exception:
            return (None, None)

    m.askcolor = askcolor
    return m


def _build_scrolledtext(tk_mod):
    m = types.ModuleType("tkinter.scrolledtext")
    m.ScrolledText = Text
    return m


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------
END = "end"
INSERT = "insert"
CURRENT = "current"
ANCHOR = "anchor"
ALL = "all"
NONE = "none"
LEFT = "left"
RIGHT = "right"
TOP = "top"
BOTTOM = "bottom"
CENTER = "center"
N = "n"
S = "s"
E = "e"
W = "w"
NW = "nw"
NE = "ne"
SW = "sw"
SE = "se"
NS = "ns"
EW = "ew"
NSEW = "nsew"
X = "x"
Y = "y"
BOTH = "both"
WORD = "word"
CHAR = "char"
NORMAL = "normal"
DISABLED = "disabled"
ACTIVE = "active"
HIDDEN = "hidden"
READONLY = "readonly"
TRUE = 1
FALSE = 0
YES = 1
NO = 0
ON = 1
OFF = 0
VERTICAL = "vertical"
HORIZONTAL = "horizontal"
RAISED = "raised"
SUNKEN = "sunken"
FLAT = "flat"
GROOVE = "groOVE" if False else "groove"
SOLID = "solid"
RIDGE = "ridge"
BROWSE = "browse"
SINGLE = "single"
MULTIPLE = "multiple"
EXTENDED = "extended"
SEL_FIRST = "sel.first"
SEL_LAST = "sel.last"
CASCADE = "cascade"
CHECKBUTTON = "checkbutton"
COMMANDS = "command"
RADIOBUTTON = "radiobutton"
SEPARATOR = "separator"
LEFTBUTTON = 1
MIDDLEBUTTON = 2
RIGHTBUTTON = 3
DISABLE = 0
NORMAL_STATE = 1
ACTIVE_STATE = 2


def mainloop(n=0):
    # event loop is the browser itself
    pass


def _reset():
    for w in list(_windows):
        try:
            w.destroy()
        except Exception:
            pass
    _windows[:] = []
    global _default_root
    _default_root = None


# ----------------------------------------------------------------
# Assemble the module
# ----------------------------------------------------------------
ttk_mod = _build_ttk()
mb_mod = _build_messagebox()
sd_mod = _build_simpledialog()
fd_mod = _build_filedialog()
font_mod = _build_font()
cc_mod = _build_colorchooser()

tk = types.ModuleType("tkinter")

# widgets
tk.Tk = Tk
tk.Toplevel = Toplevel
tk.Frame = Frame
tk.LabelFrame = LabelFrame
tk.Label = Label
tk.Button = Button
tk.Entry = Entry
tk.Text = Text
tk.Checkbutton = Checkbutton
tk.Radiobutton = Radiobutton
tk.Scale = Scale
tk.Spinbox = Spinbox
tk.Listbox = Listbox
tk.Canvas = Canvas
tk.Menu = Menu
tk.Menubutton = Button
tk.PhotoImage = PhotoImage
tk.BitmapImage = BitmapImage
tk.Scrollbar = Scrollbar
tk.Widget = BaseWidget
tk.BaseWidget = BaseWidget
tk.Misc = BaseWidget
tk.TclError = TclError
tk.StringVar = StringVar
tk.IntVar = IntVar
tk.DoubleVar = DoubleVar
tk.BooleanVar = BooleanVar
tk.Variable = Variable

# constants
for _name, _val in list(globals().items()):
    if _name.isupper() or _name in ("mainloop", "_reset"):
        setattr(tk, _name, _val)
tk.mainloop = mainloop
tk._reset = _reset
tk._default_root = None
tk.TclVersion = 8.6
tk.TkVersion = 8.6
tk.ttk = ttk_mod
tk.messagebox = mb_mod
tk.simpledialog = sd_mod
tk.filedialog = fd_mod
tk.font = font_mod
tk.colorchooser = cc_mod

sys.modules["tkinter"] = tk
sys.modules["tkinter.ttk"] = ttk_mod
sys.modules["tkinter.constants"] = tk
sys.modules["tkinter.messagebox"] = mb_mod
sys.modules["tkinter.simpledialog"] = sd_mod
sys.modules["tkinter.filedialog"] = fd_mod
sys.modules["tkinter.font"] = font_mod
sys.modules["tkinter.colorchooser"] = cc_mod
sys.modules["tkinter.scrolledtext"] = _build_scrolledtext(tk)
