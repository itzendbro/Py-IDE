"""DOM-stub test for py/tkinter_shim.py — runs under plain CPython."""
import sys, types, traceback

class Style:
    def __init__(self): self._s = {}
    def __setattr__(self, k, v): self.__dict__[k.replace("-", "_")] = v
    def __getattr__(self, k): return self.__dict__.get(k, "")

class FakeClassList:
    def __init__(self, el): self.el = el; self._set = set((el.className or "").split())
    def _sync(self): self.el.className = " ".join(sorted(self._set))
    def add(self, *n): self._set.update(n); self._sync()
    def remove(self, *n):
        for x in n: self._set.discard(x)
        self._sync()
    def toggle(self, n, force=None):
        if force is None: force = n not in self._set
        if force: self._set.add(n)
        else: self._set.discard(n)
        self._sync(); return force
    def contains(self, n): return n in self._set

class FakeElement:
    def __init__(self, tag):
        self.tag = tag; self.className = ""; self.children = []; self.style = Style()
        self.value = ""; self.textContent = ""; self.type = "text"; self.checked = False
        self.disabled = False; self.readOnly = False; self.spellcheck = True; self.id = ""
        self.offsetWidth = 200; self.offsetHeight = 100; self.offsetLeft = 0; self.offsetTop = 0
        self.clientWidth = 800; self.clientHeight = 600; self.width = 300; self.height = 200
        self.rows = 4; self.min = "0"; self.max = "100"; self.step = "1"
        self._attrs = {}; self._listeners = {}; self.classList = FakeClassList(self)
    def appendChild(self, c): self.children.append(c); return c
    def addEventListener(self, ev, fn): self._listeners.setdefault(ev, []).append(fn)
    def removeEventListener(self, ev, fn): self._listeners.get(ev, []).remove(fn)
    def setAttribute(self, k, v): self._attrs[k] = v
    def remove(self): pass
    def focus(self): pass
    def click(self): pass
    def getContext(self, kind):
        class Ctx:
            def __getattr__(self, n): return lambda *a, **k: None
        return Ctx()
    def setSelectionRange(self, a, b): pass
    def querySelectorAll(self, sel): return []

class FakeDoc:
    def __init__(self):
        self._byid = {"tk-desktop": FakeElement("div")}; self.body = FakeElement("body")
    def createElement(self, tag): return FakeElement(tag)
    def getElementById(self, i): return self._byid.get(i)

class FakeConsole:
    def error(self, *a): print("CONSOLE.ERROR:", *a)
    def log(self, *a): pass

class FakeWindow:
    def __init__(self):
        self.console = FakeConsole(); self.innerWidth = 1200; self.innerHeight = 800
        self.__tk_clip = ""; self._timers = {}; self._tid = 0
    def setTimeout(self, fn, ms): self._tid += 1; self._timers[self._tid] = fn; return self._tid
    def clearTimeout(self, tid): self._timers.pop(tid, None)
    def alert(self, *a): pass
    def confirm(self, *a): return True
    def prompt(self, *a): return "test"
    def addEventListener(self, *a, **k): pass

win = FakeWindow(); doc = FakeDoc()
js = types.ModuleType("js"); js.document = doc; js.window = win
sys.modules["js"] = js
g = {"window": win, "document": doc, "console": win.console}
win.globalThis = g
exec(compile(open("/home/user/Py-IDE/py/tkinter_shim.py").read(), "shim", "exec"), g)
tk = sys.modules["tkinter"]

fails = []
def check(name, fn):
    try:
        fn(); print("PASS", name)
    except Exception:
        fails.append(name); print("FAIL", name); traceback.print_exc()

def t1():
    root = tk.Tk(); root.title("Hello"); root.geometry("300x200+50+60"); root.configure(bg="white")
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    lbl = tk.Label(root, text="Hi", fg="red", font=("Arial", 14, "bold")); lbl.pack(pady=5)
    var = tk.IntVar(value=0)
    btn = tk.Button(root, text="Go", command=lambda: var.set(var.get() + 1))
    btn.pack(side="left", fill="x", expand=True); btn.invoke(); assert var.get() == 1
    root.update(); assert root.winfo_exists(); root.mainloop()
check("Tk/Label/Button/pack", t1)

def t2():
    root = tk.Toplevel()
    e = tk.Entry(root, show="*"); e.insert(0, "abc"); assert e.get() == "abc"; e.delete(0, "end"); assert e.get() == ""
    t = tk.Text(root, width=40, height=5); t.insert("1.0", "line1\nline2"); assert "line1" in t.get("1.0", "end")
    t.delete("1.0", "2.0"); e.bind("<Return>", lambda ev: None); root.bind("<Button-1>", lambda ev: None)
check("Entry/Text/bind", t2)

def t3():
    root = tk.Tk()
    cv = tk.StringVar(value="off"); cb = tk.Checkbutton(root, text="A", variable=cv, onvalue="on", offvalue="off")
    cb.invoke(); assert cv.get() == "on"
    rv = tk.IntVar(value=1)
    tk.Radiobutton(root, text="One", variable=rv, value=1)
    r2 = tk.Radiobutton(root, text="Two", variable=rv, value=2); r2.invoke(); assert rv.get() == 2
    lb = tk.Listbox(root, selectmode="multiple"); lb.insert("end", "x", "y", "z")
    assert lb.size() == 3 and lb.get(0) == "x"; lb.selection_set(0, 1); assert lb.curselection() == (0, 1); lb.delete(1)
    sc = tk.Scale(root, from_=0, to=10); sc.set(5); assert float(sc.get()) == 5.0
    tk.Spinbox(root, from_=0, to=9)
check("Check/Radio/Listbox/Scale/Spinbox", t3)

def t4():
    root = tk.Tk(); c = tk.Canvas(root, width=300, height=200, bg="white"); c.pack()
    l = c.create_line(0, 0, 100, 100, fill="red", width=2)
    r = c.create_rectangle(10, 10, 50, 50, fill="blue", outline="black")
    o = c.create_oval(60, 60, 120, 120); c.create_polygon(0, 0, 10, 0, 5, 10)
    c.create_text(100, 100, text="hi", anchor="nw"); c.create_arc(0, 0, 50, 50, start=0, extent=180, style="pieslice")
    c.coords(l, 1, 1, 90, 90); c.itemconfig(r, fill="green"); c.move(o, 5, 5); c.delete("all")
check("Canvas", t4)

def t5():
    root = tk.Tk(); f = tk.LabelFrame(root, text="Group"); f.grid(row=0, column=0, sticky="nsew")
    tk.Label(f, text="inside").grid(row=0, column=0, padx=4, pady=4)
    b = tk.Button(f, text="p"); b.place(x=10, y=20, width=80, height=30); b.place_forget()
check("grid/place/LabelFrame", t5)

def t6():
    root = tk.Tk(); m = tk.Menu(root); m.add_command(label="Quit"); m.add_separator(); root.config(menu=m)
    tk.PhotoImage(file="x.png")
    sv = tk.StringVar(value="s"); dv = tk.DoubleVar(value=1.5); bv = tk.BooleanVar(value=True)
    fired = []; sv.trace_add("write", lambda *a: fired.append(1)); sv.set("changed"); assert fired == [1]
    tid = root.after(100, lambda: None); root.after_cancel(tid)
    assert dv.get() == 1.5 and bv.get() is True
check("Menu/Photo/Var/after", t6)

def t7():
    from tkinter import ttk
    root = tk.Tk(); ttk.Style().configure("TButton"); ttk.Frame(root).pack(); ttk.Label(root, text="ttk").pack()
    ttk.Button(root, text="b").pack(); ttk.Entry(root).pack()
    cb = ttk.Combobox(root, values=["a", "b"]); cb.set("a"); assert cb.get() == "a"
    nb = ttk.Notebook(root); p1 = ttk.Frame(root); p2 = ttk.Frame(root)
    nb.add(p1, text="One"); nb.add(p2, text="Two"); nb.select(1)
    pb = ttk.Progressbar(root, maximum=100); pb.step(20); pb.set(50)
    ttk.Separator(root, orient="horizontal").pack()
    tv = ttk.Treeview(root, columns=("a", "b")); tv.heading("#0", text="Item"); tv.heading("a", text="A")
    tv.insert("", "end", text="row1", values=("1", "2")); ttk.Scrollbar(root, orient="vertical")
check("ttk", t7)

def t8():
    from tkinter import messagebox, simpledialog, filedialog, font, colorchooser
    messagebox.showinfo("t", "m"); messagebox.askyesno("t", "m"); messagebox.askquestion("t", "m")
    simpledialog.askstring("t", "p"); simpledialog.askinteger("t", "p")
    filedialog.askopenfilename()
    f = font.Font(family="Arial", size=12, weight="bold"); f.measure("hi"); f.metrics()
    colorchooser.askcolor("#ff0000")
check("dialogs/font/color", t8)

def t9():
    root = tk.Tk(); count = tk.IntVar()
    def inc(): count.set(count.get() + 1)
    tk.Label(root, textvariable=count, font=("Helvetica", 24, "bold")).pack(pady=10)
    tk.Button(root, text="+", width=10, command=inc).pack()
    for _ in range(3): inc()
    assert count.get() == 3
    from tkinter.scrolledtext import ScrolledText
    st = ScrolledText(root); st.insert("end", "scroll")
    tk._reset()
check("beginner patterns/reset", t9)

print()
if fails:
    print("FAILURES:", fails); sys.exit(1)
print("ALL SHIM TESTS PASSED")
