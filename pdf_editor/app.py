from __future__ import annotations

import json
import shutil
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .digital_signing import (
    DigitalSigningError,
    create_self_signed_pkcs12,
    sign_pdf_with_pkcs12,
)
from .i18n import tr as _
from .model import Placement, ViewTransform, size_from_bottom_right
from .pdf_ops import (
    PdfEditorError,
    export_pdf,
    normalized_text_placement,
    page_sizes,
    render_page,
)


BG = "#f3f4f6"
PANEL = "#ffffff"
INK = "#17202a"
MUTED = "#667085"
ACCENT = "#2563eb"
SELECTION = "#ef4444"
RESIZE_HANDLE_SIZE = 6
PRESETS = {
    "signature": ("preset_signature", 160.0),
    "initials": ("preset_initials", 70.0),
    "approved": ("preset_approved", 150.0),
}


class PdfSignatureEditor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(_("window_title"))
        self.geometry("1180x780")
        self.minsize(920, 620)
        self.configure(bg=BG)

        self.pdf_path: Path | None = None
        self.sizes: list[tuple[float, float]] = []
        self.page_index = 0
        self.placements: list[Placement] = []
        self.selected: Placement | None = None
        self.rendered_page: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.transform: ViewTransform | None = None
        self.drag_offset = (0.0, 0.0)
        self.interaction_mode: str | None = None

        self.custom_text = tk.StringVar(value="Lu et approuvé")
        self.font_size = tk.DoubleVar(value=14.0)
        self.item_size = tk.DoubleVar(value=100.0)
        self.digital_sign_enabled = tk.BooleanVar(value=False)
        self.page_label = tk.StringVar(value=_("no_document"))
        self.status = tk.StringVar(value=_("start_status"))
        self.certificate_path = self._load_certificate_path()
        self.preset_paths = self._load_presets()
        self.preset_status = {
            key: tk.StringVar() for key in PRESETS
        }

        self._configure_style()
        self._build_ui()
        self._refresh_preset_labels()
        self.bind("<Delete>", lambda _event: self.delete_selected())
        self.bind("<BackSpace>", lambda _event: self.delete_selected())
        self.bind("<Left>", lambda _event: self.change_page(-1))
        self.bind("<Right>", lambda _event: self.change_page(1))

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure(
            "Title.TLabel",
            background=PANEL,
            foreground=INK,
            font=("Helvetica", 15, "bold"),
        )
        style.configure(
            "TLabel", background=PANEL, foreground=INK, font=("Helvetica", 11)
        )
        style.configure(
            "Muted.TLabel", background=PANEL, foreground=MUTED, font=("Helvetica", 10)
        )
        style.configure("TButton", font=("Helvetica", 11), padding=(12, 8))
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            font=("Helvetica", 11, "bold"),
            padding=(12, 9),
        )
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, style="Panel.TFrame", padding=(14, 10))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text=_("open_pdf"), command=self.open_pdf).pack(side="left")
        ttk.Button(
            toolbar, text=_("save_as"), command=self.save_pdf,
            style="Accent.TButton"
        ).pack(side="left", padx=(8, 0))
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=16
        )
        ttk.Button(toolbar, text="‹", width=3, command=lambda: self.change_page(-1)).pack(
            side="left"
        )
        ttk.Label(toolbar, textvariable=self.page_label).pack(side="left", padx=10)
        ttk.Button(toolbar, text="›", width=3, command=lambda: self.change_page(1)).pack(
            side="left"
        )
        ttk.Separator(toolbar, orient="vertical").pack(
            side="left", fill="y", padx=16
        )
        ttk.Checkbutton(
            toolbar,
            text=_("digital_sign_pdf"),
            variable=self.digital_sign_enabled,
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text=_("certificate_button"),
            command=self.manage_certificate,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            toolbar, text=_("copy_notice"),
            style="Muted.TLabel"
        ).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        sidebar = ttk.Frame(body, style="Panel.TFrame", padding=18, width=290)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ttk.Label(sidebar, text=_("graphic_presets"), style="Title.TLabel").pack(
            anchor="w", pady=(0, 14)
        )
        ttk.Label(
            sidebar,
            text=_("preset_explanation"),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 9))
        for key, (label_key, _width) in PRESETS.items():
            row = ttk.Frame(sidebar, style="Panel.TFrame")
            row.pack(fill="x", pady=4)
            info = ttk.Frame(row, style="Panel.TFrame")
            info.pack(side="left", fill="x", expand=True)
            ttk.Label(info, text=_(label_key)).pack(anchor="w")
            ttk.Label(
                info, textvariable=self.preset_status[key], style="Muted.TLabel"
            ).pack(anchor="w")
            ttk.Button(
                row,
                text=_("add"),
                width=8,
                command=lambda preset_key=key: self.add_preset(preset_key),
            ).pack(side="right")
            ttk.Button(
                row,
                text="⋯",
                width=3,
                command=lambda preset_key=key: self.configure_preset(preset_key),
            ).pack(side="right", padx=(0, 4))

        ttk.Separator(sidebar).pack(fill="x", pady=18)
        ttk.Label(sidebar, text=_("custom_text")).pack(anchor="w")
        ttk.Entry(sidebar, textvariable=self.custom_text).pack(fill="x", pady=(7, 7))
        ttk.Button(
            sidebar, text=_("add_text"), command=self.add_custom_text
        ).pack(fill="x")

        ttk.Label(sidebar, text=_("text_size")).pack(anchor="w", pady=(14, 0))
        ttk.Scale(
            sidebar,
            from_=8,
            to=36,
            variable=self.font_size,
            command=self.on_font_size,
        ).pack(fill="x", pady=(3, 0))

        ttk.Separator(sidebar).pack(fill="x", pady=18)
        ttk.Label(sidebar, text=_("selected_size")).pack(
            anchor="w"
        )
        ttk.Scale(
            sidebar,
            from_=25,
            to=250,
            variable=self.item_size,
            command=self.on_item_size,
        ).pack(fill="x", pady=(3, 0))
        ttk.Button(
            sidebar, text=_("delete_item"), command=self.delete_selected
        ).pack(fill="x", pady=(12, 0))
        ttk.Button(
            sidebar, text=_("clear_page"), command=self.clear_page
        ).pack(fill="x", pady=(6, 0))

        ttk.Label(
            sidebar,
            text=_("usage_tip"),
            style="Muted.TLabel",
            wraplength=250,
            justify="left",
        ).pack(side="bottom", anchor="w")

        canvas_frame = ttk.Frame(body, padding=14)
        canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(
            canvas_frame,
            bg="#d7dbe2",
            highlightthickness=0,
            cursor="arrow",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<Button-1>", self.on_mouse_down)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        status_bar = ttk.Frame(self, style="Panel.TFrame", padding=(14, 7))
        status_bar.pack(fill="x")
        ttk.Label(status_bar, textvariable=self.status, style="Muted.TLabel").pack(
            anchor="w"
        )

    @property
    def config_path(self) -> Path:
        return Path.home() / ".pdf-signature-editor" / "presets.json"

    @property
    def settings_path(self) -> Path:
        return Path.home() / ".pdf-signature-editor" / "settings.json"

    def _load_certificate_path(self) -> Path | None:
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            value = raw.get("certificate_path")
            path = Path(value) if isinstance(value, str) else None
            return path if path and path.is_file() else None
        except (OSError, ValueError, TypeError):
            return None

    def _save_certificate_path(self) -> None:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "certificate_path": (
                    str(self.certificate_path) if self.certificate_path else None
                )
            }
            self.settings_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showwarning(
                _("settings_not_saved"),
                _("settings_not_saved_detail", error=exc),
            )

    def _load_presets(self) -> dict[str, Path]:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            return {
                key: Path(value)
                for key, value in raw.items()
                if key in PRESETS and isinstance(value, str) and Path(value).is_file()
            }
        except (OSError, ValueError, TypeError):
            return {}

    def _save_presets(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {key: str(path) for key, path in self.preset_paths.items()}
            self.config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showwarning(
                _("settings_not_saved"),
                _("settings_not_saved_detail", error=exc),
            )

    def _refresh_preset_labels(self) -> None:
        for key in PRESETS:
            path = self.preset_paths.get(key)
            if path and path.is_file():
                self.preset_status[key].set(path.name)
            else:
                self.preset_status[key].set(_("image_not_selected"))

    def _choose_image(self, title: str) -> Path | None:
        filename = filedialog.askopenfilename(
            title=title,
            filetypes=[
                (_("images"), "*.png *.jpg *.jpeg"),
                (_("transparent_png"), "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
            ],
        )
        if not filename:
            return None
        path = Path(filename)
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            messagebox.showerror(
                _("invalid_image"), _("image_read_failed", error=exc)
            )
            return None
        return path

    def configure_preset(self, key: str) -> None:
        label_key, _width = PRESETS[key]
        label = _(label_key)
        path = self._choose_image(_("choose_image", label=label))
        if not path:
            return
        self.preset_paths[key] = self._store_preset_image(key, path)
        self._save_presets()
        self._refresh_preset_labels()
        self.status.set(_("preset_configured", label=label))

    def _store_preset_image(self, key: str, source: Path) -> Path:
        destination = self.config_path.parent / f"{key}{source.suffix.lower()}"
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            return destination
        except OSError as exc:
            messagebox.showwarning(
                _("image_copy_failed"),
                _("using_original", error=exc),
            )
            return source

    def manage_certificate(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(_("certificate_dialog_title"))
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()

        content = ttk.Frame(dialog, style="Panel.TFrame", padding=20)
        content.pack(fill="both", expand=True)
        certificate_status = tk.StringVar()

        def refresh() -> None:
            if self.certificate_path and self.certificate_path.is_file():
                certificate_status.set(
                    _("current_certificate", name=self.certificate_path.name)
                )
            else:
                certificate_status.set(_("no_certificate"))

        ttk.Label(
            content,
            textvariable=certificate_status,
            style="Title.TLabel",
            wraplength=420,
        ).pack(anchor="w")
        ttk.Label(
            content,
            text=_("certificate_warning"),
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(8, 18))
        ttk.Button(
            content,
            text=_("select_certificate"),
            command=lambda: (self.select_certificate(dialog), refresh()),
        ).pack(fill="x")
        ttk.Button(
            content,
            text=_("create_certificate"),
            command=lambda: (self.create_certificate(dialog), refresh()),
        ).pack(fill="x", pady=(8, 0))
        ttk.Button(
            content,
            text=_("close"),
            command=dialog.destroy,
        ).pack(fill="x", pady=(18, 0))
        refresh()
        dialog.wait_visibility()
        dialog.focus_set()
        self.wait_window(dialog)

    def select_certificate(self, parent: tk.Misc | None = None) -> None:
        dialog_parent = parent or self
        filename = filedialog.askopenfilename(
            parent=dialog_parent,
            title=_("certificate_dialog_title"),
            filetypes=[
                (_("certificate_files"), "*.p12 *.pfx"),
                (_("all_files"), "*.*"),
            ],
        )
        if not filename:
            return
        self.certificate_path = Path(filename)
        self.digital_sign_enabled.set(True)
        self._save_certificate_path()
        self.status.set(
            _("certificate_selected_status", name=self.certificate_path.name)
        )

    def create_certificate(self, parent: tk.Misc | None = None) -> None:
        dialog_parent = parent or self
        name = simpledialog.askstring(
            _("create_certificate"),
            _("certificate_name_prompt"),
            parent=dialog_parent,
        )
        if name is None:
            return
        email = simpledialog.askstring(
            _("create_certificate"),
            _("certificate_email_prompt"),
            parent=dialog_parent,
        )
        if email is None:
            return
        password = simpledialog.askstring(
            _("create_certificate"),
            _("certificate_password_prompt"),
            parent=dialog_parent,
            show="*",
        )
        if password is None:
            return
        confirmation = simpledialog.askstring(
            _("create_certificate"),
            _("certificate_password_confirm"),
            parent=dialog_parent,
            show="*",
        )
        if confirmation is None:
            return
        if not name.strip() or not password:
            messagebox.showerror(
                _("required_field"),
                _("name_and_password_required"),
                parent=dialog_parent,
            )
            return
        if password != confirmation:
            messagebox.showerror(
                _("passwords_differ"),
                _("passwords_differ_detail"),
                parent=dialog_parent,
            )
            return

        filename = filedialog.asksaveasfilename(
            parent=dialog_parent,
            title=_("save_certificate_title"),
            initialfile="personal-signing-certificate.p12",
            defaultextension=".p12",
            filetypes=[(_("certificate_files"), "*.p12 *.pfx")],
        )
        if not filename:
            return
        path = Path(filename)
        try:
            create_self_signed_pkcs12(
                path,
                common_name=name,
                email=email,
                password=password,
            )
        except DigitalSigningError as exc:
            messagebox.showerror(
                _("certificate_create_failed"),
                str(exc),
                parent=dialog_parent,
            )
            return

        self.certificate_path = path
        self.digital_sign_enabled.set(True)
        self._save_certificate_path()
        self.status.set(_("certificate_created_status", name=path.name))
        messagebox.showinfo(
            _("certificate_created"),
            _("certificate_created_detail", path=path),
            parent=dialog_parent,
        )

    def add_preset(self, key: str) -> None:
        if not self._require_document():
            return
        label_key, preferred_width = PRESETS[key]
        label = _(label_key)
        path = self.preset_paths.get(key)
        if not path or not path.is_file():
            path = self._choose_image(_("choose_image", label=label))
            if not path:
                return
            self.preset_paths[key] = self._store_preset_image(key, path)
            path = self.preset_paths[key]
            self._save_presets()
            self._refresh_preset_labels()
        self._add_image(path, preferred_width, label)

    def open_pdf(self) -> None:
        filename = filedialog.askopenfilename(
            title=_("open_pdf_title"),
            filetypes=[(_("pdf_documents"), "*.pdf"), (_("all_files"), "*.*")],
        )
        if not filename:
            return
        try:
            path = Path(filename)
            sizes = page_sizes(path)
            rendered = render_page(path, 1)
        except PdfEditorError as exc:
            messagebox.showerror(_("open_failed"), str(exc))
            return

        self.pdf_path = path
        self.sizes = sizes
        self.page_index = 0
        self.placements.clear()
        self.selected = None
        self.rendered_page = rendered
        self._update_page_label()
        self.status.set(_("document_loaded", name=path.name))
        self.redraw()

    def _update_page_label(self) -> None:
        if self.pdf_path:
            self.page_label.set(
                _("page_count", current=self.page_index + 1, total=len(self.sizes))
            )
        else:
            self.page_label.set(_("no_document"))

    def change_page(self, delta: int) -> None:
        if not self.pdf_path:
            return
        target = min(max(0, self.page_index + delta), len(self.sizes) - 1)
        if target == self.page_index:
            return
        try:
            rendered = render_page(self.pdf_path, target + 1)
        except PdfEditorError as exc:
            messagebox.showerror(_("display_error"), str(exc))
            return
        self.page_index = target
        self.rendered_page = rendered
        self.selected = None
        self._update_page_label()
        self.redraw()

    def _require_document(self) -> bool:
        if self.pdf_path:
            return True
        messagebox.showinfo(_("no_document"), _("open_first"))
        return False

    def add_text(self, text: str) -> None:
        if not self._require_document():
            return
        page_width, page_height = self.sizes[self.page_index]
        placement = normalized_text_placement(
            self.page_index, 0, 0, text, float(self.font_size.get())
        )
        placement.x = (page_width - placement.width) / 2
        placement.y = (page_height - placement.height) / 2
        self.placements.append(placement)
        self.selected = placement
        self.item_size.set(100)
        self.status.set(_("text_added"))
        self.redraw()

    def add_custom_text(self) -> None:
        text = self.custom_text.get().strip()
        if not text:
            messagebox.showinfo(_("empty_text"), _("enter_text"))
            return
        self.add_text(text)

    def _add_image(self, image_path: Path, preferred_width: float, label: str) -> None:
        try:
            with Image.open(image_path) as image:
                width_px, height_px = image.size
        except Exception as exc:
            messagebox.showerror(
                _("invalid_image"), _("image_read_failed", error=exc)
            )
            return

        page_width, page_height = self.sizes[self.page_index]
        width = min(preferred_width, page_width * 0.35)
        height = width * height_px / max(1, width_px)
        placement = Placement(
            kind="image",
            page_index=self.page_index,
            x=(page_width - width) / 2,
            y=(page_height - height) / 2,
            width=width,
            height=height,
            image_path=image_path,
        )
        self.placements.append(placement)
        self.selected = placement
        self.item_size.set(100)
        self.status.set(_("image_added", label=label))
        self.redraw()

    def on_font_size(self, _value: str) -> None:
        if not self.selected or self.selected.kind != "text":
            return
        old_width = max(self.selected.width, 0.01)
        new_size = float(self.font_size.get())
        replacement = normalized_text_placement(
            self.selected.page_index,
            self.selected.x,
            self.selected.y,
            self.selected.text,
            new_size,
        )
        replacement.x -= (replacement.width - old_width) / 2
        self.selected.x = replacement.x
        self.selected.width = replacement.width
        self.selected.height = replacement.height
        self.selected.font_size = replacement.font_size
        self._clamp_selected()
        self.redraw()

    def on_item_size(self, value: str) -> None:
        if not self.selected or self.selected.kind != "image":
            return
        scale = float(value) / 100.0
        if not hasattr(self.selected, "_base_size"):
            setattr(
                self.selected, "_base_size",
                (self.selected.width, self.selected.height),
            )
        base_width, base_height = getattr(self.selected, "_base_size")
        center_x = self.selected.x + self.selected.width / 2
        center_y = self.selected.y + self.selected.height / 2
        self.selected.width = base_width * scale
        self.selected.height = base_height * scale
        self.selected.x = center_x - self.selected.width / 2
        self.selected.y = center_y - self.selected.height / 2
        self._clamp_selected()
        self.redraw()

    def _clamp_selected(self) -> None:
        if self.selected and self.transform:
            self.selected.x, self.selected.y = self.transform.clamp_box(
                self.selected.x,
                self.selected.y,
                self.selected.width,
                self.selected.height,
            )

    def delete_selected(self) -> None:
        if self.selected and self.selected in self.placements:
            self.placements.remove(self.selected)
            self.selected = None
            self.status.set(_("item_deleted"))
            self.redraw()

    def clear_page(self) -> None:
        if not self._require_document():
            return
        current = [p for p in self.placements if p.page_index == self.page_index]
        if not current:
            return
        if not messagebox.askyesno(
            _("clear_page"), _("clear_page_question")
        ):
            return
        self.placements = [
            p for p in self.placements if p.page_index != self.page_index
        ]
        self.selected = None
        self.redraw()

    def _placement_at(self, canvas_x: float, canvas_y: float) -> Placement | None:
        if not self.transform:
            return None
        pdf_x, pdf_y = self.transform.canvas_to_pdf(canvas_x, canvas_y)
        visible = [
            p for p in self.placements if p.page_index == self.page_index
        ]
        for placement in reversed(visible):
            if placement.contains(pdf_x, pdf_y):
                return placement
        return None

    def on_mouse_down(self, event: tk.Event) -> None:
        if self._resize_handle_hit(event.x, event.y):
            self.interaction_mode = "resize"
            self.status.set(_("resize_started"))
            self.canvas.configure(cursor="crosshair")
            return

        placement = self._placement_at(event.x, event.y)
        self.selected = placement
        if placement and self.transform:
            self.interaction_mode = "move"
            pdf_x, pdf_y = self.transform.canvas_to_pdf(event.x, event.y)
            self.drag_offset = (pdf_x - placement.x, pdf_y - placement.y)
            if placement.kind == "text":
                self.font_size.set(placement.font_size)
            else:
                self.item_size.set(100)
                setattr(placement, "_base_size", (placement.width, placement.height))
            self.status.set(_("item_selected"))
        else:
            self.interaction_mode = None
        self.redraw()

    def on_mouse_drag(self, event: tk.Event) -> None:
        if not self.selected or not self.transform:
            return
        pdf_x, pdf_y = self.transform.canvas_to_pdf(event.x, event.y)
        if self.interaction_mode == "resize" and self.selected.kind == "image":
            self.selected.width, self.selected.height = size_from_bottom_right(
                self.selected,
                pdf_x,
                pdf_y,
                self.transform.page_width,
                self.transform.page_height,
            )
            self.redraw()
            return
        if self.interaction_mode != "move":
            return
        self.selected.x = pdf_x - self.drag_offset[0]
        self.selected.y = pdf_y - self.drag_offset[1]
        self._clamp_selected()
        self.redraw()

    def on_mouse_up(self, _event: tk.Event) -> None:
        if (
            self.interaction_mode == "resize"
            and self.selected
            and self.selected.kind == "image"
        ):
            setattr(
                self.selected,
                "_base_size",
                (self.selected.width, self.selected.height),
            )
            self.item_size.set(100)
            self.status.set(_("image_resized"))
        self.interaction_mode = None
        self.canvas.configure(cursor="arrow")
        self.redraw()

    def on_mouse_move(self, event: tk.Event) -> None:
        if self.interaction_mode:
            return
        cursor = "crosshair" if self._resize_handle_hit(event.x, event.y) else "arrow"
        self.canvas.configure(cursor=cursor)

    def _resize_handle_hit(self, canvas_x: float, canvas_y: float) -> bool:
        if (
            not self.selected
            or self.selected.kind != "image"
            or self.selected.page_index != self.page_index
            or not self.transform
        ):
            return False
        right, bottom = self.transform.pdf_to_canvas(
            self.selected.x + self.selected.width,
            self.selected.y + self.selected.height,
        )
        tolerance = RESIZE_HANDLE_SIZE + 5
        return (
            abs(canvas_x - right) <= tolerance
            and abs(canvas_y - bottom) <= tolerance
        )

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._overlay_photos = []
        if not self.rendered_page or not self.pdf_path:
            width = max(1, self.canvas.winfo_width())
            height = max(1, self.canvas.winfo_height())
            self.canvas.create_text(
                width / 2,
                height / 2 - 15,
                text=_("canvas_open_pdf"),
                fill="#475467",
                font=("Helvetica", 20, "bold"),
            )
            self.canvas.create_text(
                width / 2,
                height / 2 + 20,
                text=_("local_notice"),
                fill="#667085",
                font=("Helvetica", 12),
            )
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        image_width, image_height = self.rendered_page.size
        scale = min(
            (canvas_width - 40) / image_width,
            (canvas_height - 40) / image_height,
        )
        scale = max(0.05, scale)
        display_size = (
            max(1, int(image_width * scale)),
            max(1, int(image_height * scale)),
        )
        preview = self.rendered_page.resize(display_size, Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview)
        left = (canvas_width - display_size[0]) / 2
        top = (canvas_height - display_size[1]) / 2
        self.canvas.create_rectangle(
            left + 4,
            top + 5,
            left + display_size[0] + 5,
            top + display_size[1] + 6,
            fill="#aeb4be",
            outline="",
        )
        self.canvas.create_image(left, top, image=self.preview_photo, anchor="nw")

        page_width, page_height = self.sizes[self.page_index]
        pdf_scale = display_size[0] / page_width
        self.transform = ViewTransform(
            page_width, page_height, left, top, pdf_scale
        )

        for placement in self.placements:
            if placement.page_index != self.page_index:
                continue
            self._draw_placement(placement)

    def _draw_placement(self, placement: Placement) -> None:
        assert self.transform is not None
        x, y = self.transform.pdf_to_canvas(placement.x, placement.y)
        width = placement.width * self.transform.scale
        height = placement.height * self.transform.scale

        if placement.kind == "text":
            font_px = max(7, int(placement.font_size * self.transform.scale))
            self.canvas.create_text(
                x,
                y + height / 2,
                text=placement.text,
                anchor="w",
                fill="#15171a",
                font=("Helvetica", font_px, "italic"),
            )
        elif placement.image_path:
            try:
                with Image.open(placement.image_path) as image:
                    rgba = image.convert("RGBA")
                    resized = rgba.resize(
                        (max(1, int(width)), max(1, int(height))),
                        Image.Resampling.LANCZOS,
                    )
                photo = ImageTk.PhotoImage(resized)
                self._overlay_photos.append(photo)
                self.canvas.create_image(x, y, image=photo, anchor="nw")
            except Exception:
                self.canvas.create_rectangle(
                    x, y, x + width, y + height, fill="#fee2e2", outline="#ef4444"
                )

        if placement is self.selected:
            self.canvas.create_rectangle(
                x - 3,
                y - 3,
                x + width + 3,
                y + height + 3,
                outline=SELECTION,
                width=2,
                dash=(5, 3),
            )
            if placement.kind == "image":
                right = x + width
                bottom = y + height
                self.canvas.create_rectangle(
                    right - RESIZE_HANDLE_SIZE,
                    bottom - RESIZE_HANDLE_SIZE,
                    right + RESIZE_HANDLE_SIZE,
                    bottom + RESIZE_HANDLE_SIZE,
                    fill=SELECTION,
                    outline="white",
                    width=2,
                )

    def save_pdf(self) -> None:
        if not self._require_document() or not self.pdf_path:
            return
        if self.digital_sign_enabled.get() and (
            not self.certificate_path or not self.certificate_path.is_file()
        ):
            messagebox.showinfo(
                _("certificate_required"),
                _("certificate_required_detail"),
            )
            self.manage_certificate()
            if not self.certificate_path or not self.certificate_path.is_file():
                return

        suggested = f"{self.pdf_path.stem}-signed.pdf"
        filename = filedialog.asksaveasfilename(
            title=_("save_title"),
            initialfile=suggested,
            defaultextension=".pdf",
            filetypes=[(_("pdf_documents"), "*.pdf")],
        )
        if not filename:
            return
        output_path = Path(filename)
        if output_path.resolve() == self.pdf_path.resolve():
            messagebox.showwarning(
                _("choose_other_name"),
                _("original_not_overwritten"),
            )
            return

        certificate_password: str | None = None
        if self.digital_sign_enabled.get():
            certificate_password = simpledialog.askstring(
                _("certificate_dialog_title"),
                _("signing_password_prompt"),
                parent=self,
                show="*",
            )
            if certificate_password is None:
                return

        try:
            if self.digital_sign_enabled.get():
                assert self.certificate_path is not None
                assert certificate_password is not None
                with tempfile.TemporaryDirectory(
                    prefix="pdf-sign-editor-signing-"
                ) as temp_dir:
                    unsigned_path = Path(temp_dir) / "unsigned.pdf"
                    signed_path = Path(temp_dir) / "signed.pdf"
                    export_pdf(self.pdf_path, unsigned_path, self.placements)
                    sign_pdf_with_pkcs12(
                        unsigned_path,
                        signed_path,
                        self.certificate_path,
                        certificate_password,
                    )
                    shutil.copy2(signed_path, output_path)
            else:
                export_pdf(self.pdf_path, output_path, self.placements)
        except DigitalSigningError as exc:
            messagebox.showerror(_("digital_sign_failed"), str(exc))
            return
        except PdfEditorError as exc:
            messagebox.showerror(_("save_failed"), str(exc))
            return

        if self.digital_sign_enabled.get():
            self.status.set(_("digital_signed_status", name=output_path.name))
            messagebox.showinfo(
                _("document_saved"),
                _("digital_signed_detail", path=output_path),
            )
        else:
            self.status.set(_("document_saved_status", name=output_path.name))
            messagebox.showinfo(
                _("document_saved"),
                _("copy_created", path=output_path),
            )


def main() -> None:
    app = PdfSignatureEditor()
    app.mainloop()


if __name__ == "__main__":
    main()
