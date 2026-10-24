"""Recipes pages of the panel: the list (with watch switches) and the editor.

Mixed into PanelWindow; uses its stack, header and widgets. All it does is emit signals the
controller acts on (recipe_saved, recipe_deleted, recipe_watch); it never touches files itself
except asking the user for folders.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from ...core.formats import CATEGORIES, FORMATS
from ...core.recipes import RENAME_HELP, Recipe, default_name, example_name
from . import style as st

FIELD_CSS = (f"QLineEdit,QComboBox{{background:rgba(255,255,255,12);border:1px solid rgba(255,255,255,30);"
             f"border-radius:10px;padding:6px 10px;color:{st.INK};selection-background-color:{st.SWITCH_ON}}}"
             f"QLineEdit:focus,QComboBox:focus{{border:1px solid {st.SWITCH_ON}}}"
             "QComboBox::drop-down{border:none;width:22px}"
             f"QComboBox QAbstractItemView{{background:#12141c;color:{st.INK};border:1px solid rgba(255,255,255,30);"
             f"selection-background-color:rgba(255,255,255,30);outline:none}}")
SCROLL_CSS = ("QScrollArea{background:transparent}QScrollArea>QWidget>QWidget{background:transparent}"
              "QScrollBar:vertical{background:transparent;width:8px;margin:2px}"
              "QScrollBar::handle:vertical{background:rgba(255,255,255,40);border-radius:3px;min-height:24px}"
              "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page{height:0;background:none}")


class RecipeRow(QAbstractButton):
    """Name + what it does; click to edit. The watch switch sits on the right."""

    def __init__(self, recipe: Recipe, parent=None):
        super().__init__(parent)
        self.r = recipe
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"Edit recipe {recipe.name}")
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self._hover = True; self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False; self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect())
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 13))
            p.drawRoundedRect(r, 12, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(st.kind_color(self.r.target))
        p.drawEllipse(QPointF(12, 18), 4, 4)
        avail = r.width() - 26 - 56
        fn = st.font(13, 500)
        p.setFont(fn)
        p.setPen(QColor(st.INK))
        p.drawText(QRectF(26, 8, avail, 20), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(fn).elidedText(self.r.name, Qt.ElideRight, avail))
        fs = st.font(11)
        p.setFont(fs)
        p.setPen(QColor(st.DIM))
        p.drawText(QRectF(26, 27, avail, 18), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetricsF(fs).elidedText(self.r.summary(), Qt.ElideRight, avail))


def _field(widget):
    widget.setStyleSheet(FIELD_CSS)
    widget.setFont(st.font(13))
    widget.setFixedHeight(36)
    return widget


class RecipePagesMixin:
    """Methods for PanelWindow (needs: stack, back_btn, mini, title, _label, Switch, PrimaryButton,
    _SegButton, _LinkButton, _GhostButton and the recipe_* signals)."""

    def _page(self, attr: str) -> QVBoxLayout:
        old = getattr(self, attr, None)
        page = QWidget()
        if old is not None:
            idx = self.stack.indexOf(old)
            self.stack.insertWidget(idx, page)
            self.stack.removeWidget(old)
            old.deleteLater()
        else:
            self.stack.addWidget(page)
        setattr(self, attr, page)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        return v

    # ------------------------------------------------------------- list
    def show_recipes(self, recipes: list[Recipe]):
        from .panel import PrimaryButton, Switch, _label
        self._recipes = recipes
        v = self._page("recipes_pg")
        if not recipes:
            msg = _label("Save a conversion you do often. Then it's one click on the orb, a right-click in "
                         "Explorer, or automatic for a folder you choose.", 13, st.DIM)
            msg.setWordWrap(True)
            msg.setContentsMargins(8, 8, 8, 0)
            v.addWidget(msg)
            v.addStretch(1)
        else:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setStyleSheet(SCROLL_CSS)
            host = QWidget()
            hv = QVBoxLayout(host)
            hv.setContentsMargins(0, 0, 4, 0)
            hv.setSpacing(2)
            self.recipe_switches = {}
            for r in recipes:
                row = RecipeRow(r)
                row.clicked.connect(lambda _=False, rr=r: self.show_recipe_editor(rr, self._editor_ctx))
                if r.watch_dir:
                    sw = Switch(row)
                    sw.setChecked(r.watching)
                    sw.setAccessibleName(f"Watch {r.watch_dir}")
                    sw.setToolTip(f"Watch {r.watch_dir}")
                    sw.move(0, 14)
                    row.resizeEvent = lambda e, s=sw, w=row: s.move(w.width() - 48, 14)
                    sw.toggled.connect(lambda on, rid=r.id: self.recipe_watch.emit(rid, on))
                    self.recipe_switches[r.id] = sw
                hv.addWidget(row)
            hv.addStretch(1)
            sc.setWidget(host)
            v.addWidget(sc, 1)
        tip = _label("Tip: on the All formats page, pick a format and choose Save as recipe.", 11, st.LABEL)
        tip.setWordWrap(True)
        tip.setContentsMargins(6, 0, 6, 0)
        v.addWidget(tip)
        new = PrimaryButton("New recipe")
        new.setEnabled(len(recipes) < 30)
        new.clicked.connect(lambda: self.show_recipe_editor(None, self._editor_ctx))
        v.addWidget(new)
        self._back_to = None
        self.stack.setCurrentWidget(self.recipes_pg)
        self.back_btn.show()
        self.mini.hide()
        self.title.setText("Recipes")

    # ------------------------------------------------------------- editor
    def show_recipe_editor(self, recipe: Recipe | None, ctx: dict, preset: dict | None = None):
        """ctx: {"targets": [keys], "options_fn": target -> option specs}. preset: target/options/
        name for "Save as recipe" from the All formats page."""
        from .panel import PrimaryButton, Switch, _GhostButton, _label, _LinkButton, _SegButton
        is_new = recipe is None
        r = recipe or Recipe(name="", target=(preset or {}).get("target") or "pdf",
                             options=dict((preset or {}).get("options") or {}),
                             sources=list((preset or {}).get("sources") or []))
        if preset and preset.get("name"):
            r.name = preset["name"]
        self._editing = r
        self._edit_dirs = {"save": r.save_dir, "watch": r.watch_dir}
        v = self._page("editor_pg")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet(SCROLL_CSS)
        host = QWidget()
        f = QVBoxLayout(host)
        f.setContentsMargins(6, 0, 10, 6)
        f.setSpacing(6)

        def head(text):
            lab = _label(text.upper(), 11, st.LABEL, 600, 0.08)
            lab.setContentsMargins(0, 6, 0, 0)
            f.addWidget(lab)

        head("Name")
        self.ed_name = _field(QLineEdit(r.name))
        self.ed_name.setMaxLength(60)
        self.ed_name.setPlaceholderText(default_name(r.target))
        f.addWidget(self.ed_name)

        head("Convert to")
        self.ed_target = _field(QComboBox())
        targets = ctx["targets"]
        for cat, _cl in CATEGORIES:
            for k in [k for k in FORMATS if k in targets and FORMATS[k].category == cat]:
                self.ed_target.addItem(f"{FORMATS[k].tag}  ·  {FORMATS[k].label}", k)
        i = self.ed_target.findData(r.target)
        self.ed_target.setCurrentIndex(max(0, i))
        f.addWidget(self.ed_target)
        self.ed_opts_host = QWidget()
        self.ed_opts = QVBoxLayout(self.ed_opts_host)
        self.ed_opts.setContentsMargins(0, 2, 0, 0)
        self.ed_opts.setSpacing(6)
        f.addWidget(self.ed_opts_host)

        head("Save to")
        row = QHBoxLayout()
        grp = QButtonGroup(host)
        self.ed_next = _SegButton("Next to original", "next")
        self.ed_dir = _SegButton("A folder", "dir")
        for b in (self.ed_next, self.ed_dir):
            grp.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        f.addLayout(row)
        self.ed_dir_link = _LinkButton("")
        self.ed_dir_link.clicked.connect(lambda: self._pick_dir("save"))
        f.addWidget(self.ed_dir_link)
        (self.ed_dir if r.save_dir else self.ed_next).setChecked(True)
        self.ed_dir.clicked.connect(lambda: self._edit_dirs["save"] or self._pick_dir("save"))
        grp.buttonClicked.connect(lambda _b: self._sync_editor())

        head("File name")
        self.ed_rename = _field(QLineEdit(r.rename))
        self.ed_rename.setPlaceholderText("Usual name, e.g. {name} {date}")
        self.ed_rename.textChanged.connect(lambda _t: self._sync_editor())
        f.addWidget(self.ed_rename)
        hint = _label(RENAME_HELP, 11, st.LABEL)
        hint.setWordWrap(True)
        f.addWidget(hint)
        self.ed_example = _label("", 11, st.DIM)
        self.ed_example.setWordWrap(True)
        f.addWidget(self.ed_example)

        head("Watch a folder")
        row = QHBoxLayout()
        lab = _label("Convert new files that arrive", 13, st.SOFT_TEXT)
        row.addWidget(lab, 1)
        self.ed_watch = Switch()
        self.ed_watch.setAccessibleName("Watch a folder")
        self.ed_watch.setChecked(r.watching and bool(r.watch_dir))
        self.ed_watch.toggled.connect(lambda on: on and not self._edit_dirs["watch"] and self._pick_dir("watch"))
        self.ed_watch.toggled.connect(lambda _on: self._sync_editor())
        row.addWidget(self.ed_watch)
        f.addLayout(row)
        self.ed_watch_link = _LinkButton("")
        self.ed_watch_link.clicked.connect(lambda: self._pick_dir("watch"))
        f.addWidget(self.ed_watch_link)
        self.ed_watch_note = _label("Files already in the folder are left alone. Runs while FileMorph is open; "
                                    "files added while it was closed are done when it starts.", 11, st.LABEL)
        self.ed_watch_note.setWordWrap(True)
        f.addWidget(self.ed_watch_note)
        f.addStretch(1)
        sc.setWidget(host)
        v.addWidget(sc, 1)

        btns = QHBoxLayout()
        if not is_new:
            dele = _GhostButton("Delete")
            dele.setFixedWidth(96)
            dele.clicked.connect(lambda: self.recipe_deleted.emit(r.id))
            btns.addWidget(dele)
        save = PrimaryButton("Save recipe")
        save.clicked.connect(self._save_recipe)
        btns.addWidget(save, 1)
        v.addLayout(btns)

        self._options_fn = ctx["options_fn"]
        self.ed_target.currentIndexChanged.connect(lambda _i: self._target_changed())
        self._target_changed(initial=True)
        self._back_to = "recipes"
        self.stack.setCurrentWidget(self.editor_pg)
        self.back_btn.show()
        self.mini.hide()
        self.title.setText("New recipe" if is_new else "Edit recipe")
        self.ed_name.setFocus()

    def _target_changed(self, initial: bool = False):
        from .panel import _SegButton, _clear, _label
        key = self.ed_target.currentData()
        if not self.ed_name.text().strip() or not initial:
            self.ed_name.setPlaceholderText(default_name(key))
        _clear(self.ed_opts)
        self.ed_opt_widgets = {}
        values = self._editing.options if initial or key == self._editing.target else {}
        for spec in self._options_fn(key):
            kind, skey, title = spec[0], spec[1], spec[2]
            if kind == "switch":
                continue  # "combine into one PDF" is a choice for one batch, not a recipe
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(_label(title, 13, st.SOFT_TEXT))
            hl.addStretch(1)
            if kind == "slider":
                s = QSlider(Qt.Horizontal)
                s.setRange(50, 100)
                s.setFixedWidth(130)
                try:
                    s.setValue(int(values.get(skey, 90)))
                except (TypeError, ValueError):
                    s.setValue(90)
                s.setStyleSheet("QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,40);border-radius:2px}"
                                f"QSlider::sub-page:horizontal{{background:{st.SWITCH_ON};border-radius:2px}}"
                                "QSlider::handle:horizontal{background:#fff;width:16px;height:16px;margin:-6px 0;"
                                "border-radius:8px}")
                val = _label(str(s.value()), 12, st.DIM)
                val.setFixedWidth(28)
                s.valueChanged.connect(lambda x, lb=val: lb.setText(str(x)))
                hl.addWidget(s)
                hl.addWidget(val)
                self.ed_opt_widgets[skey] = s
            elif kind == "seg":
                choices, default = spec[3], spec[4]
                cur = values.get(skey, default)
                grp = QButtonGroup(row)
                for text, value in choices:
                    b = _SegButton(text, value)
                    b.setChecked(value == cur)
                    grp.addButton(b)
                    hl.addWidget(b)
                if not grp.checkedButton():
                    grp.buttons()[0].setChecked(True)
                self.ed_opt_widgets[skey] = grp
            self.ed_opts.addWidget(row)
        self.ed_opts_host.setVisible(bool(self.ed_opt_widgets))
        self._sync_editor()

    def _pick_dir(self, which: str):
        cur = self._edit_dirs.get(which) or str(Path.home())
        title = "Save converted files to" if which == "save" else "Folder to watch"
        d = QFileDialog.getExistingDirectory(None, title, cur)
        if d:
            self._edit_dirs[which] = d
        elif which == "save" and not self._edit_dirs["save"]:
            self.ed_next.setChecked(True)
        elif which == "watch" and not self._edit_dirs["watch"]:
            self.ed_watch.setChecked(False)
        self._sync_editor()

    def _sync_editor(self):
        save_dir = self._edit_dirs.get("save") if self.ed_dir.isChecked() else ""
        self.ed_dir_link.setVisible(bool(save_dir))
        if save_dir:
            self.ed_dir_link.setText(f"{Path(save_dir).name or save_dir}  ·  change")
        wd = self._edit_dirs.get("watch")
        self.ed_watch_link.setVisible(bool(wd))
        if wd:
            self.ed_watch_link.setText(f"{Path(wd).name or wd}  ·  change")
        self.ed_watch_note.setVisible(self.ed_watch.isChecked())
        key = self.ed_target.currentData()
        if key:
            self.ed_example.setText("e.g. " + example_name(self.ed_rename.text(), key))

    def editor_values(self) -> Recipe:
        """The recipe as the editor currently shows it."""
        r = self._editing
        key = self.ed_target.currentData()
        opts = {}
        for k, w in self.ed_opt_widgets.items():
            if isinstance(w, QSlider):
                opts[k] = w.value()
            elif isinstance(w, QButtonGroup) and w.checkedButton():
                opts[k] = w.checkedButton().value
        wd = self._edit_dirs.get("watch") or ""
        return Recipe(name=self.ed_name.text().strip() or default_name(key), target=key, options=opts,
                      save_dir=(self._edit_dirs.get("save") or "") if self.ed_dir.isChecked() else "",
                      rename=self.ed_rename.text().strip(), watch_dir=wd,
                      watching=self.ed_watch.isChecked() and bool(wd), watch_since=r.watch_since, id=r.id,
                      sources=[s for s in r.sources if key in self._targets_of(s)])

    def _targets_of(self, src: str) -> set:
        fn = getattr(self, "_editor_ctx", {}).get("targets_of")
        return fn(src) if fn else set(FORMATS)

    def _save_recipe(self):
        self.recipe_saved.emit(self.editor_values())

    def go_back(self):
        if getattr(self, "_back_to", None) == "recipes" and hasattr(self, "_recipes"):
            self.show_recipes(self._recipes)
        else:
            self.show_home()

