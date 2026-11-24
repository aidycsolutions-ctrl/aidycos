"""GTK calculator window."""

from __future__ import annotations

import re
from decimal import Decimal

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from .branding import apply_branding, load_logo_pixbuf
from .engine import CalcError, evaluate, format_number, repeat_suffix, toggle_sign
from .state import load_state, save_state

TEAL = "#0B3D4A"
MINT = "#3DDC97"
BG = "#F4F7F8"
INK = "#102027"

_OPS = set("+-*/^×÷−:")
_DECIMAL_RE = re.compile(r"(?:\d+[.,]\d*|[.,]\d+)$")


def _install_style() -> None:
    css = Gtk.CssProvider()
    css.load_from_data(
        f"""
        window.aidycalc, window.aidycalc * {{ color: {INK}; }}
        window.aidycalc {{ background: {BG}; }}
        .calc-header {{ background: {TEAL}; padding: 10px 12px; }}
        .calc-header label {{ color: #ffffff; }}
        .calc-display {{ background: #ffffff; padding: 8px 12px 10px; }}
        .calc-expr {{ color: #5b6b73; font-size: 13px; }}
        .calc-result {{ color: {INK}; font-size: 28px; font-weight: bold; }}
        .calc-error {{ color: #a33; font-size: 18px; font-weight: bold; }}
        .calc-memory {{ color: {MINT}; font-weight: bold; }}
        .calc-history {{ background: #ffffff; }}
        .calc-history row {{ padding: 2px 8px; }}
        button.calc-key {{
            min-height: 40px;
            min-width: 64px;
            padding: 4px 6px;
            border-radius: 8px;
            font-weight: 600;
        }}
        button.calc-num {{ background: #ffffff; }}
        button.calc-fn {{ background: #E8EEF0; }}
        button.calc-op, button.calc-op label {{ background: {TEAL}; color: #ffffff; }}
        button.calc-eq, button.calc-eq label {{ background: {MINT}; color: {TEAL}; }}
        button.calc-mem {{ background: #d7e4ea; }}
        button.calc-header-btn, button.calc-header-btn label {{
            background: transparent;
            color: #ffffff;
            border: 1px solid rgba(255,255,255,0.35);
            border-radius: 6px;
        }}
        """.encode()
    )
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )


class CalcWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Calculadora")
        self.set_default_size(380, 640)
        self.set_border_width(0)
        self.get_style_context().add_class("aidycalc")
        apply_branding(self)

        stored = load_state()
        self.angle = str(stored["angle"])
        self.memory = Decimal(str(stored["memory"]))
        self.history: list[dict[str, str]] = list(stored["history"])  # type: ignore[arg-type]
        self.expression = ""
        self.value: Decimal | None = None
        self.fresh = False
        self._repeat: tuple[str, str] | None = None
        self._display_is_error = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)
        root.pack_start(self._build_header(), False, False, 0)
        root.pack_start(self._build_display(), False, False, 0)
        root.pack_start(self._build_history(), False, False, 0)

        pad = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pad.set_border_width(10)
        root.pack_start(pad, True, True, 0)
        pad.pack_start(self._build_keys(), True, True, 0)

        self.connect("key-press-event", self._on_key)
        self.refresh()
        self._reload_history()

    def _build_header(self) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.get_style_context().add_class("calc-header")
        logo = load_logo_pixbuf(28)
        if logo is not None:
            header.pack_start(Gtk.Image.new_from_pixbuf(logo), False, False, 0)
        title = Gtk.Label()
        title.set_markup("<span size='large'><b>Calculadora</b></span>")
        title.set_xalign(0)
        header.pack_start(title, False, False, 0)
        self.memory_label = Gtk.Label(label="")
        self.memory_label.get_style_context().add_class("calc-memory")
        header.pack_start(self.memory_label, False, False, 0)
        header.pack_start(Gtk.Label(label=""), True, True, 0)

        self.angle_button = Gtk.Button(label="DEG")
        self.angle_button.get_style_context().add_class("calc-header-btn")
        self.angle_button.set_tooltip_text("Grados o radianes para sen, cos y tan")
        self.angle_button.connect("clicked", lambda _button: self.toggle_angle())
        header.pack_start(self.angle_button, False, False, 0)

        copy = Gtk.Button(label="Copiar")
        copy.get_style_context().add_class("calc-header-btn")
        copy.set_tooltip_text("Copiar el resultado (Ctrl+C)")
        copy.connect("clicked", lambda _button: self.copy_result())
        header.pack_start(copy, False, False, 0)
        return header

    def _build_display(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("calc-display")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.expr_label = Gtk.Label(label="")
        self.expr_label.set_xalign(1)
        self.expr_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.expr_label.get_style_context().add_class("calc-expr")
        row.pack_start(self.expr_label, True, True, 0)
        back = Gtk.Button(label="⌫")
        back.set_relief(Gtk.ReliefStyle.NONE)
        back.set_tooltip_text("Borrar")
        back.connect("clicked", lambda _button: self.backspace())
        row.pack_start(back, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.result_label = Gtk.Label(label="0")
        self.result_label.set_xalign(1)
        self.result_label.set_selectable(False)
        self.result_label.get_style_context().add_class("calc-result")
        box.pack_start(self.result_label, False, False, 0)
        return box

    def _build_history(self) -> Gtk.ScrolledWindow:
        self.history_scroll = Gtk.ScrolledWindow()
        self.history_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.history_scroll.set_size_request(-1, 88)
        self.history_scroll.get_style_context().add_class("calc-history")
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.history_scroll.add(self.history_list)
        return self.history_scroll

    def _build_keys(self) -> Gtk.Grid:
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        rows = [
            [("C", "fn"), ("(", "fn"), (")", "fn"), ("%", "fn")],
            [("sin", "fn"), ("cos", "fn"), ("tan", "fn"), ("√", "fn")],
            [("ln", "fn"), ("log", "fn"), ("x²", "fn"), ("xʸ", "fn")],
            [("π", "fn"), ("e", "fn"), ("n!", "fn"), ("1/x", "fn")],
            [("7", "num"), ("8", "num"), ("9", "num"), ("÷", "op")],
            [("4", "num"), ("5", "num"), ("6", "num"), ("×", "op")],
            [("1", "num"), ("2", "num"), ("3", "num"), ("−", "op")],
            [("±", "num"), ("0", "num"), (",", "num"), ("+", "op")],
            [("MC", "mem"), ("MR", "mem"), ("M+", "mem"), ("M−", "mem")],
        ]
        for row_index, row in enumerate(rows):
            for column, (label, kind) in enumerate(row):
                button = Gtk.Button(label=label)
                button.get_style_context().add_class("calc-key")
                button.get_style_context().add_class(f"calc-{kind}")
                button.connect("clicked", lambda _button, text=label: self.on_action(text))
                grid.attach(button, column, row_index, 1, 1)
        equals = Gtk.Button(label="=")
        equals.get_style_context().add_class("calc-key")
        equals.get_style_context().add_class("calc-eq")
        equals.connect("clicked", lambda _button: self.equals())
        grid.attach(equals, 0, len(rows), 4, 1)
        return grid

    def on_action(self, action: str) -> None:
        if action == "C":
            self.clear_all()
        elif action == "±":
            self._replace_expression(toggle_sign(self.expression if not self.fresh else self._shown_value()))
        elif action == "x²":
            self._continue_from_result()
            self._append("^2")
        elif action == "xʸ":
            self._continue_from_result()
            self._append("^")
        elif action == "1/x":
            base = self._shown_value() if self.fresh or not self.expression else self.expression
            self._replace_expression(f"1/({base})" if base else "1/")
        elif action == "n!":
            self._continue_from_result()
            self._append("!")
        elif action in {"sin", "cos", "tan", "ln", "log"}:
            self._insert_callable(action)
        elif action == "√":
            self._insert_prefix("√")
        elif action == "π":
            self._insert_value("π")
        elif action == "e":
            self._insert_value("e")
        elif action == "MC":
            self.memory = Decimal(0)
            self._persist()
            self.refresh()
        elif action == "MR":
            self._insert_value(format_number(self.memory))
        elif action == "M+":
            self._add_memory(Decimal(1))
        elif action == "M−":
            self._add_memory(Decimal(-1))
        elif action in _OPS or action in {"+", "−", "×", "÷"}:
            self._insert_operator(action)
        else:
            self._insert_value(action)
        self.refresh()

    def _insert_callable(self, name: str) -> None:
        if self.fresh:
            self.expression = ""
            self.fresh = False
        self._append(f"{name}(")

    def _insert_prefix(self, text: str) -> None:
        if self.fresh:
            current = self._shown_value()
            self._replace_expression(text + current if current else text)
            return
        self._append(text)

    def _insert_value(self, text: str) -> None:
        if text in {"%", "!"}:
            self._continue_from_result()
        elif self.fresh:
            self.expression = ""
            self.fresh = False
        if text in {".", ","} and _DECIMAL_RE.search(self.expression.replace(" ", "")):
            return
        if text in {".", ","} and (
            not self.expression or self.expression[-1] in _OPS or self.expression[-1] in "(√"
        ):
            text = "0" + text
        self._append(text)

    def _insert_operator(self, operator: str) -> None:
        if self.fresh and self.value is not None:
            self.expression = format_number(self.value)
            self.fresh = False
        if not self.expression:
            self.expression = "0"
        if self.expression[-1] in _OPS:
            if operator in {"-", "−"} and self.expression[-1] not in {"-", "−"}:
                self.expression += operator
            else:
                self.expression = self.expression[:-1] + operator
        else:
            self.expression += operator
        self.fresh = False

    def _continue_from_result(self) -> None:
        if self.fresh and self.value is not None:
            self.expression = format_number(self.value)
            self.fresh = False

    def _append(self, text: str) -> None:
        if len(self.expression) + len(text) > 1000:
            return
        self.expression += text
        self.fresh = False

    def _replace_expression(self, text: str) -> None:
        self.expression = text
        self.fresh = False

    def _shown_value(self) -> str:
        if self.value is None:
            return ""
        return format_number(self.value)

    def clear_all(self) -> None:
        self.expression = ""
        self.value = None
        self.fresh = False
        self._repeat = None
        self.refresh()

    def backspace(self) -> None:
        if self.fresh:
            self.clear_all()
            return
        self.expression = self.expression[:-1]
        self.refresh()

    def equals(self) -> None:
        expression = self.expression.strip()
        if self.fresh and self._repeat and self.value is not None:
            operator, rhs = self._repeat
            expression = f"{format_number(self.value)}{operator}{rhs}"
            self.expression = expression
        if not expression:
            return
        try:
            value = evaluate(
                expression,
                angle=self.angle,
                ans=self.value,
                memory=self.memory,
            )
        except CalcError as exc:
            self._show_error(str(exc))
            return
        rendered = format_number(value)
        if not re.fullmatch(r"-?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?", expression):
            self.history.append({"expr": expression, "result": rendered})
            self.history = self.history[-40:]
            self._reload_history()
        try:
            self._repeat = repeat_suffix(expression)
        except CalcError:
            self._repeat = None
        self.value = value
        self.expression = expression
        self.fresh = True
        self._display_is_error = False
        self._persist()
        self._show_result(expression, rendered)

    def _add_memory(self, sign: Decimal) -> None:
        try:
            current = self._current_value()
        except CalcError as exc:
            if not exc.incomplete:
                self._show_error(str(exc))
            return
        self.memory += sign * current
        self._persist()
        self.refresh()

    def _current_value(self) -> Decimal:
        if self.fresh and self.value is not None:
            return self.value
        if not self.expression.strip():
            return self.value if self.value is not None else Decimal(0)
        return evaluate(self.expression, angle=self.angle, ans=self.value, memory=self.memory)

    def toggle_angle(self) -> None:
        self.angle = "rad" if self.angle == "deg" else "deg"
        self._persist()
        self.refresh()

    def copy_result(self) -> None:
        if self._display_is_error:
            return
        text = self.result_label.get_text() or "0"
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

    def paste(self) -> None:
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if not text:
            return
        cleaned = "".join(text.split())
        if not cleaned or len(cleaned) > 1000:
            return
        if not re.fullmatch(r"[0-9A-Za-zπ+\-*/^%().,;×÷−–:!√_]+", cleaned):
            return
        if self.fresh:
            self.expression = cleaned
            self.fresh = False
        else:
            self._append(cleaned)
        self.refresh()

    def refresh(self) -> None:
        self.angle_button.set_label("RAD" if self.angle == "rad" else "DEG")
        self.memory_label.set_text("M" if self.memory != 0 else "")
        if self.fresh and self.value is not None:
            self._show_result(self.expression, format_number(self.value))
            return
        self.expr_label.set_text(self.expression)
        if not self.expression:
            self._display_is_error = False
            self.result_label.set_text("0")
            self.result_label.get_style_context().remove_class("calc-error")
            self.result_label.get_style_context().add_class("calc-result")
            return
        try:
            value = evaluate(
                self.expression,
                angle=self.angle,
                ans=self.value,
                memory=self.memory,
            )
        except CalcError as exc:
            self._display_is_error = not exc.incomplete
            self.result_label.set_text(self.expression if exc.incomplete else str(exc))
            style = self.result_label.get_style_context()
            if exc.incomplete:
                style.remove_class("calc-error")
                style.add_class("calc-result")
            else:
                style.remove_class("calc-result")
                style.add_class("calc-error")
            return
        self._show_result(self.expression, format_number(value))

    def _show_result(self, expression: str, rendered: str) -> None:
        self._display_is_error = False
        self.expr_label.set_text(expression)
        self.result_label.set_text(rendered)
        style = self.result_label.get_style_context()
        style.remove_class("calc-error")
        style.add_class("calc-result")

    def _show_error(self, message: str) -> None:
        self._display_is_error = True
        self.fresh = False
        self.result_label.set_text(message)
        style = self.result_label.get_style_context()
        style.remove_class("calc-result")
        style.add_class("calc-error")

    def _reload_history(self) -> None:
        for child in list(self.history_list.get_children()):
            self.history_list.remove(child)
        if not self.history:
            self.history_scroll.hide()
            return
        self.history_scroll.show()
        for item in reversed(self.history[-12:]):
            label = Gtk.Label(label=f"{item['expr']}  =  {item['result']}")
            label.set_xalign(1)
            label.get_style_context().add_class("calc-expr")
            row = Gtk.ListBoxRow()
            row.add(label)
            row.calc_item = item  # type: ignore[attr-defined]
            row.connect("button-press-event", self._on_history_click)
            self.history_list.add(row)
        self.history_list.show_all()

    def _on_history_click(self, row: Gtk.ListBoxRow, _event: Gdk.EventButton) -> bool:
        item = getattr(row, "calc_item", None)
        if not isinstance(item, dict):
            return False
        self.expression = str(item.get("expr") or "")
        self.fresh = False
        self._repeat = None
        self.refresh()
        return True

    def _persist(self) -> None:
        save_state(angle=self.angle, memory=self.memory, history=self.history)

    def _on_key(self, _widget: Gtk.Window, event: Gdk.EventKey) -> bool:
        modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
        if modifiers & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval in (Gdk.KEY_c, Gdk.KEY_C):
                self.copy_result()
                return True
            if event.keyval in (Gdk.KEY_v, Gdk.KEY_V):
                self.paste()
                return True
            return False
        name = Gdk.keyval_name(event.keyval) or ""
        if name in {"Return", "KP_Enter", "KP_Equal"}:
            self.equals()
            return True
        if name == "equal" and not modifiers & Gdk.ModifierType.SHIFT_MASK:
            self.equals()
            return True
        if name == "Escape":
            self.clear_all()
            return True
        if name == "BackSpace":
            self.backspace()
            return True
        if name == "Delete":
            self.clear_all()
            return True
        text = event.string or ""
        if name in {"KP_Add"}:
            text = "+"
        elif name in {"KP_Subtract"}:
            text = "-"
        elif name in {"KP_Multiply"}:
            text = "*"
        elif name in {"KP_Divide"}:
            text = "/"
        elif name in {"KP_Decimal", "KP_Separator"}:
            text = ","
        elif name.startswith("KP_") and name[3:].isdigit():
            text = name[3:]
        if text and re.fullmatch(r"[0-9A-Za-zπ+\-*/^%().,;×÷−–:!√_]+", text):
            self._insert_typed(text)
            self.refresh()
            return True
        return False

    def _insert_typed(self, text: str) -> None:
        if text in _OPS:
            self._insert_operator(text)
            return
        self._insert_value(text)


def run() -> int:
    _install_style()
    window = CalcWindow()
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    if not window.history:
        window.history_scroll.hide()
    window.present()
    Gtk.main()
    return 0
