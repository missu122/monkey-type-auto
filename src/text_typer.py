from __future__ import annotations

import ctypes
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageEnhance, ImageGrab
except ImportError:
    Image = None
    ImageEnhance = None
    ImageGrab = None


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
VK_ESCAPE = 0x1B
VK_F8 = 0x77
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_INSERT = 0x2D
VK_CONTROL = 0x11
VK_V = 0x56

TYPE_MODE_CHARS = "Печатать символами"
TYPE_MODE_PASTE = "Вставить целиком"

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = (wintypes.INT,)
user32.GetAsyncKeyState.restype = wintypes.SHORT


@dataclass(frozen=True)
class TypingConfig:
    text: str
    wpm: int
    minimize_before_start: bool
    type_mode: str

    @property
    def char_delay(self) -> float:
        chars_per_minute = max(1, self.wpm) * 5
        return 60 / chars_per_minute


@dataclass(frozen=True)
class ScreenRegion:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def label(self) -> str:
        return f"{self.left},{self.top} {self.width}x{self.height}"


class TextTyperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Text Typer")
        self.geometry("760x540")
        self.minsize(620, 430)
        self.configure(bg="#121820")
        self._icon_photo: tk.PhotoImage | None = None
        self._set_window_icon()

        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.screen_region: ScreenRegion | None = None

        self.wpm_var = tk.StringVar(value="80")
        self.ocr_interval_var = tk.StringVar(value="1.5")
        self.mode_var = tk.StringVar(value=TYPE_MODE_PASTE)
        self.minimize_var = tk.BooleanVar(value=True)
        self.russian_fix_var = tk.BooleanVar(value=False)
        self.strict_ocr_var = tk.BooleanVar(value=True)
        self.repeat_ocr_var = tk.BooleanVar(value=True)
        self.lowercase_ocr_var = tk.BooleanVar(value=True)
        self.force_russian_var = tk.BooleanVar(value=True)
        self.gray_text_only_var = tk.BooleanVar(value=True)
        self.enter_after_word_var = tk.BooleanVar(value=True)
        self.enter_every_10_words_var = tk.BooleanVar(value=False)
        self.custom_tag_enabled_var = tk.BooleanVar(value=False)
        self.custom_tag_var = tk.StringVar(value="")
        self.region_var = tk.StringVar(value="Область чтения не выбрана")
        self.status_var = tk.StringVar(value="Готово. Для live выбери область и нажми Live OCR.")

        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _set_window_icon(self) -> None:
        assets_dir = self._app_root() / "assets"
        ico_path = assets_dir / "app_icon.ico"
        png_path = assets_dir / "app_icon.png"

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("local.text_typer.default_icon")
        except Exception:
            pass

        if ico_path.exists():
            try:
                self.iconbitmap(default=str(ico_path))
            except tk.TclError:
                pass

        if png_path.exists():
            try:
                self._icon_photo = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self._icon_photo)
            except tk.TclError:
                pass

    def _app_root(self) -> Path:
        source_dir = Path(__file__).resolve().parent
        if source_dir.name == "src":
            return source_dir.parent
        return source_dir

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#121820")
        style.configure("TLabel", background="#121820", foreground="#eef3f8", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("TCheckbutton", background="#121820", foreground="#eef3f8", font=("Segoe UI", 10))
        style.configure("TEntry", fieldbackground="#202b37", foreground="#eef3f8")

        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Text Typer", style="Title.TLabel").pack(anchor="w")

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(14, 10))

        ttk.Label(controls, text="WPM").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.wpm_var, width=8).grid(row=1, column=0, sticky="w", padx=(0, 18))

        ttk.Label(controls, text="OCR sec").grid(row=0, column=1, sticky="w")
        ttk.Entry(controls, textvariable=self.ocr_interval_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(0, 18)
        )

        ttk.Label(controls, text="Режим").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=(TYPE_MODE_CHARS, TYPE_MODE_PASTE),
            state="readonly",
            width=20,
        ).grid(row=1, column=2, sticky="w", padx=(0, 18))

        ttk.Checkbutton(
            controls,
            text="Свернуть перед печатью",
            variable=self.minimize_var,
        ).grid(row=1, column=3, sticky="w", padx=(0, 18))

        ttk.Checkbutton(
            controls,
            text="Enter после слова",
            variable=self.enter_after_word_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            controls,
            text="Enter каждые 10 слов",
            variable=self.enter_every_10_words_var,
        ).grid(row=2, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Checkbutton(
            controls,
            text="Свой тег",
            variable=self.custom_tag_enabled_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.custom_tag_entry = ttk.Entry(controls, textvariable=self.custom_tag_var, width=18)
        self.custom_tag_entry.grid(row=3, column=2, columnspan=3, sticky="we", pady=(8, 0))

        self.start_button = ttk.Button(controls, text="Start", command=self._start)
        self.start_button.grid(row=1, column=4, sticky="w", padx=(0, 8))

        self.stop_button = ttk.Button(controls, text="Stop", command=self._stop, state="disabled")
        self.stop_button.grid(row=1, column=5, sticky="w")

        controls.columnconfigure(6, weight=1)

        text_actions = ttk.Frame(root)
        text_actions.pack(fill="x", pady=(0, 8))

        self.repeat_button = ttk.Button(text_actions, text="Повторение", command=self._start_repeat)
        self.repeat_button.pack(side="left", padx=(0, 8))

        ttk.Button(
            text_actions,
            text="Вставить из буфера",
            command=self._paste_from_clipboard,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            text_actions,
            text="OCR из картинки в буфере",
            command=self._ocr_from_clipboard,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            text_actions,
            text="OCR из файла",
            command=self._ocr_from_file,
        ).pack(side="left", padx=(0, 8))
        self.select_region_button = ttk.Button(
            text_actions,
            text="Выбрать область",
            command=self._select_region,
        )
        self.select_region_button.pack(side="left", padx=(0, 8))
        self.live_button = ttk.Button(
            text_actions,
            text="Live OCR",
            command=self._start_live_ocr,
        )
        self.live_button.pack(side="left", padx=(0, 8))
        ttk.Button(
            text_actions,
            text="Тест печати",
            command=self._start_test_print,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(text_actions, text="Очистить", command=self._clear_text).pack(side="left")

        ttk.Label(root, textvariable=self.region_var).pack(anchor="w", pady=(0, 8))

        self.text_box = tk.Text(
            root,
            wrap="word",
            undo=True,
            bg="#202b37",
            fg="#eef3f8",
            insertbackground="#eef3f8",
            selectbackground="#376ea8",
            relief="flat",
            padx=12,
            pady=12,
            font=("Segoe UI", 11),
        )
        self.text_box.pack(fill="both", expand=True)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(
            bottom,
            text="Start печатает текст из поля. Live OCR читает выбранную область. F8 запуск, Esc стоп.",
        ).pack(anchor="w")
        ttk.Label(bottom, textvariable=self.status_var).pack(anchor="w", pady=(6, 0))

    def _bind_shortcuts(self) -> None:
        for sequence in ("<Control-v>", "<Control-V>", "<Control-Cyrillic_em>", "<Control-Cyrillic_EM>"):
            self.bind_all(sequence, self._paste_from_clipboard_event)
        self.bind_all("<Control-KeyPress>", self._control_key_event)

    def _control_key_event(self, event: tk.Event) -> str | None:
        keysym = str(getattr(event, "keysym", "")).lower()
        char = str(getattr(event, "char", "")).lower()
        keycode = int(getattr(event, "keycode", 0) or 0)
        if keycode == VK_V or keysym in {"v", "cyrillic_em"} or char in {"v", "м"}:
            return self._paste_from_clipboard_event(event)
        return None

    def _paste_from_clipboard_event(self, event: tk.Event) -> str | None:
        if self.focus_get() is self.custom_tag_entry:
            self._paste_into_custom_tag()
            return "break"
        if self.focus_get() is self.text_box:
            self._paste_from_clipboard()
            return "break"
        return None

    def _paste_into_custom_tag(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showerror("Text Typer", "Буфер обмена пуст или недоступен.")
            return

        text = " ".join(text.split())
        if not text:
            return

        try:
            self.custom_tag_entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

        self.custom_tag_entry.insert("insert", text)
        self.custom_tag_entry.focus_set()

    def _paste_from_clipboard(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showerror("Text Typer", "Буфер обмена пуст или недоступен.")
            return

        try:
            self.text_box.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

        self.text_box.insert("insert", text)
        self.text_box.focus_set()
        self.status_var.set(f"Вставлено символов: {len(text)}")

    def _clear_text(self) -> None:
        self.text_box.delete("1.0", "end")
        self.text_box.focus_set()
        self.status_var.set("Текст очищен.")

    def _start_test_print(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        self._replace_text("test 123", "Тест готов. Открой Блокнот, кликни в него и нажми F8.", focus=False)
        self.mode_var.set(TYPE_MODE_PASTE)
        self._start()

    def _select_region(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        self.status_var.set("Выдели мышкой область с текстом.")
        self.iconify()
        self.after(300, self._open_region_selector)

    def _open_region_selector(self) -> None:
        overlay = tk.Toplevel(self)
        overlay.title("Select OCR region")
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        overlay.configure(bg="black", cursor="crosshair")

        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        start: dict[str, int | None] = {"x": None, "y": None, "root_x": None, "root_y": None}
        rect_id: dict[str, int | None] = {"id": None}

        def on_press(event: tk.Event) -> None:
            start["x"] = int(event.x)
            start["y"] = int(event.y)
            start["root_x"] = int(event.x_root)
            start["root_y"] = int(event.y_root)
            rect_id["id"] = canvas.create_rectangle(
                event.x,
                event.y,
                event.x,
                event.y,
                outline="#5cc8ff",
                width=3,
            )

        def on_drag(event: tk.Event) -> None:
            if rect_id["id"] is None or start["x"] is None or start["y"] is None:
                return
            canvas.coords(rect_id["id"], start["x"], start["y"], event.x, event.y)

        def on_release(event: tk.Event) -> None:
            if start["root_x"] is None or start["root_y"] is None:
                overlay.destroy()
                self.deiconify()
                return

            left = min(int(start["root_x"]), int(event.x_root))
            top = min(int(start["root_y"]), int(event.y_root))
            right = max(int(start["root_x"]), int(event.x_root))
            bottom = max(int(start["root_y"]), int(event.y_root))
            overlay.destroy()
            self.deiconify()

            region = ScreenRegion(left=left, top=top, right=right, bottom=bottom)
            if region.width < 30 or region.height < 15:
                messagebox.showerror("Text Typer", "Область слишком маленькая.")
                self.status_var.set("Область не выбрана.")
                return

            self.screen_region = region
            self.region_var.set(f"Область чтения: {region.label()}")
            self.status_var.set("Область выбрана. Нажми Live OCR.")

        def on_escape(event: tk.Event) -> None:
            overlay.destroy()
            self.deiconify()
            self.status_var.set("Выбор области отменён.")

        overlay.bind("<ButtonPress-1>", on_press)
        overlay.bind("<B1-Motion>", on_drag)
        overlay.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)
        overlay.focus_force()

    def _ocr_from_clipboard(self) -> None:
        if ImageGrab is None or Image is None:
            messagebox.showerror("Text Typer", "OCR из буфера требует Pillow. Запусти через run.bat.")
            return

        try:
            clipboard_data = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showerror("Text Typer", f"Не удалось прочитать буфер: {exc}")
            return

        if clipboard_data is None:
            messagebox.showerror("Text Typer", "В буфере нет картинки. Сделай скрин и скопируй его.")
            return

        if isinstance(clipboard_data, Image.Image):
            with NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                image_path = Path(temp_file.name)
            clipboard_data.save(image_path)
            self._run_ocr_and_insert(image_path, remove_after=True)
            return

        if isinstance(clipboard_data, list):
            for item in clipboard_data:
                path = Path(item)
                if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                    self._run_ocr_and_insert(path)
                    return

        messagebox.showerror("Text Typer", "В буфере нет поддерживаемой картинки.")

    def _ocr_from_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Выбери картинку для OCR",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        self._run_ocr_and_insert(Path(file_path))

    def _run_ocr_and_insert(self, image_path: Path, *, remove_after: bool = False) -> None:
        self.status_var.set("Распознаю текст...")
        threading.Thread(
            target=self._ocr_worker,
            args=(image_path, remove_after),
            daemon=True,
        ).start()

    def _run_ocr_subprocess(self, image_path: Path, *, timeout: int = 45, gray_only: bool = False) -> str:
        tesseract_text = self._run_tesseract_ocr(image_path, timeout=timeout, gray_only=gray_only)
        if tesseract_text:
            return tesseract_text

        script_path = self._app_root() / "tools" / "ocr_win.ps1"
        if not script_path.exists():
            raise RuntimeError("Не найден tools/ocr_win.ps1.")

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                str(image_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "OCR вернул ошибку."
            raise RuntimeError(error)
        return result.stdout.strip()

    def _run_tesseract_ocr(self, image_path: Path, *, timeout: int, gray_only: bool = False) -> str:
        tesseract = self._find_tesseract()
        if tesseract is None or Image is None:
            return ""

        prepared_path: Path | None = None
        try:
            prepared_path = self._prepare_ocr_image(image_path, gray_only=gray_only)
            tessdata_dir = self._app_root() / "tessdata"
            tesseract_command = [
                str(tesseract),
                str(prepared_path),
                "stdout",
                "-l",
                "rus+eng",
                "--psm",
                "6",
            ]
            if (tessdata_dir / "rus.traineddata").exists() and (tessdata_dir / "eng.traineddata").exists():
                tesseract_command.extend(["--tessdata-dir", str(tessdata_dir)])

            result = subprocess.run(
                tesseract_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            if "Error opening data file" in result.stderr:
                result = subprocess.run(
                    [str(tesseract), str(prepared_path), "stdout", "-l", "eng", "--psm", "6"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            return ""
        finally:
            if prepared_path is not None:
                try:
                    prepared_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _find_tesseract(self) -> Path | None:
        exe = shutil.which("tesseract")
        if exe:
            return Path(exe)

        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
            self._app_root() / "tools" / "tesseract" / "tesseract.exe",
        ]
        return next((path for path in candidates if path.exists()), None)

    def _prepare_ocr_image(self, image_path: Path, *, gray_only: bool = False) -> Path:
        source = Image.open(image_path).convert("RGB")
        if gray_only:
            image = self._extract_gray_text(source)
        else:
            image = source.convert("L")
            if sum(image.histogram()[:128]) > sum(image.histogram()[128:]):
                image = Image.eval(image, lambda pixel: 255 - pixel)

        width, height = image.size
        scale = 3 if width < 1600 else 2
        image = image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
        image = ImageEnhance.Contrast(image).enhance(2.2)
        image = image.point(lambda pixel: 0 if pixel < 145 else 255)

        with NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            prepared_path = Path(temp_file.name)
        image.save(prepared_path)
        return prepared_path

    def _extract_gray_text(self, source: Image.Image) -> Image.Image:
        rgb = source.convert("RGB")
        gray = rgb.convert("L")
        median = self._median_luma(gray)
        dark_background = median < 128
        width, height = rgb.size
        output = Image.new("L", (width, height), 255)

        src = rgb.load()
        dst = output.load()
        for y in range(height):
            for x in range(width):
                r, g, b = src[x, y]
                luma = int(0.299 * r + 0.587 * g + 0.114 * b)
                saturationish = max(r, g, b) - min(r, g, b)
                near_gray = saturationish <= 38

                if dark_background:
                    is_text = near_gray and luma >= max(70, median + 22)
                else:
                    is_text = near_gray and luma <= min(185, median - 22)

                if is_text:
                    dst[x, y] = 0

        return output

    def _median_luma(self, gray: Image.Image) -> int:
        histogram = gray.histogram()
        midpoint = gray.size[0] * gray.size[1] // 2
        total = 0
        for value, count in enumerate(histogram):
            total += count
            if total >= midpoint:
                return value
        return 128

    def _ocr_worker(self, image_path: Path, remove_after: bool) -> None:
        try:
            text = self._cleanup_ocr_text(self._run_ocr_subprocess(image_path))
            if not text:
                raise RuntimeError("Текст не найден. Попробуй скрин крупнее или контрастнее.")

            self.after(0, lambda: self._replace_text(text, f"OCR: распознано символов: {len(text)}"))
        except Exception as exc:
            error_message = str(exc)
            self.after(0, lambda: messagebox.showerror("Text Typer", f"OCR не сработал: {error_message}"))
            self.after(0, lambda: self.status_var.set("OCR не сработал."))
        finally:
            if remove_after:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _replace_text(self, text: str, status: str, *, focus: bool = True) -> None:
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", text)
        if focus:
            self.text_box.focus_set()
        self.status_var.set(status)

    def _read_config(self) -> TypingConfig | None:
        text = self.text_box.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showerror("Text Typer", "Вставь текст для печати.")
            return None

        wpm = self._read_wpm()
        if wpm is None:
            return None

        return TypingConfig(
            text=text,
            wpm=wpm,
            minimize_before_start=self.minimize_var.get(),
            type_mode=self.mode_var.get(),
        )

    def _read_wpm(self) -> int | None:
        try:
            wpm = int(self.wpm_var.get().strip())
        except ValueError:
            messagebox.showerror("Text Typer", "WPM должен быть целым числом.")
            return None

        if wpm < 1 or wpm > 400:
            messagebox.showerror("Text Typer", "WPM должен быть от 1 до 400.")
            return None

        return wpm

    def _read_ocr_interval(self) -> float | None:
        try:
            interval = float(self.ocr_interval_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Text Typer", "OCR sec должен быть числом.")
            return None

        if interval < 0.5 or interval > 120:
            messagebox.showerror("Text Typer", "OCR sec должен быть от 0.5 до 120.")
            return None

        return interval

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        config = self._read_config()
        if config is None:
            return

        self.stop_event.clear()
        self._set_running_ui(True)
        self.status_var.set("Готов к печати. Кликни в нужное поле и нажми F8.")

        if config.minimize_before_start:
            self.after(250, self.iconify)

        self.worker = threading.Thread(target=self._typing_worker, args=(config,), daemon=True)
        self.worker.start()

    def _start_repeat(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        config = self._read_config()
        if config is None:
            return

        words = config.text.split()
        if not words:
            messagebox.showerror("Text Typer", "Вставь слово для повторения.")
            return

        self.stop_event.clear()
        self._set_running_ui(True)
        self.status_var.set("Повторение запущено. Для остановки нажми Stop или Esc.")

        if config.minimize_before_start:
            self.after(250, self.iconify)

        self.worker = threading.Thread(target=self._repeat_worker, args=(config, words[0]), daemon=True)
        self.worker.start()

    def _start_live_ocr(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if ImageGrab is None or Image is None:
            messagebox.showerror("Text Typer", "Live OCR требует Pillow. Запусти через run.bat.")
            return
        if self.screen_region is None:
            messagebox.showerror("Text Typer", "Сначала нажми `Выбрать область` и выдели текст на экране.")
            return

        wpm = self._read_wpm()
        if wpm is None:
            return
        interval = self._read_ocr_interval()
        if interval is None:
            return

        self.stop_event.clear()
        self._set_running_ui(True)
        self.status_var.set("Live OCR готов. Кликни в поле назначения и нажми F8.")

        if self.minimize_var.get():
            self.after(250, self.iconify)

        self.worker = threading.Thread(
            target=self._live_ocr_worker,
            args=(self.screen_region, interval, wpm, self.mode_var.get(), self.repeat_ocr_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("Остановка...")

    def _typing_worker(self, config: TypingConfig) -> None:
        try:
            self._wait_for_key_release(VK_F8)
            while not self._is_key_down(VK_F8):
                if self._should_stop():
                    self._finish("Остановлено.")
                    return
                time.sleep(0.03)
            self._wait_for_key_release(VK_F8)

            text_to_type = self._enter_after_each_word(config.text)

            if config.type_mode == TYPE_MODE_PASTE:
                self._paste_text_to_target(text_to_type)
                self._finish(f"Готово. Вставлено символов: {len(config.text)}.")
                return

            total = len(text_to_type)
            self._type_text_to_target(text_to_type, config.char_delay)
            self._finish(f"Готово. Напечатано {total} символов.")
        except Exception as exc:
            self._finish(f"Ошибка: {exc}")

    def _repeat_worker(self, config: TypingConfig, word: str) -> None:
        try:
            time.sleep(0.45)
            typed_words = 0
            while not self._should_stop():
                typed_words += 1
                self._type_text_to_target(self._format_repeat_word(word, typed_words), config.char_delay)
                if typed_words % 10 == 0:
                    self._set_status(f"Повторение: напечатано {typed_words} раз.")
            self._finish(f"Повторение остановлено. Напечатано {typed_words} раз.")
        except Exception as exc:
            self._finish(f"Ошибка повторения: {exc}")

    def _live_ocr_worker(
        self,
        region: ScreenRegion,
        interval: float,
        wpm: int,
        type_mode: str,
        repeat_ocr: bool,
    ) -> None:
        last_text = ""
        try:
            self._wait_for_key_release(VK_F8)
            while not self._is_key_down(VK_F8):
                if self._should_stop():
                    self._finish("Live OCR остановлен.")
                    return
                time.sleep(0.03)
            self._wait_for_key_release(VK_F8)

            self._set_status("OCR запущен. Читаю область...")
            while not self._should_stop():
                text = self._capture_region_text(
                    region,
                    gray_only=bool(last_text and self.gray_text_only_var.get()),
                )

                normalized = " ".join(text.split())
                text_to_type = text
                if repeat_ocr and last_text:
                    text_to_type = self._new_text_after_overlap(last_text, normalized)

                if normalized and text_to_type:
                    self.after(
                        0,
                        lambda value=text, typed_len=len(text_to_type): self._replace_text(
                            value,
                            f"Live OCR: найдено {len(value)} символов, печатаю {typed_len}",
                            focus=False,
                        ),
                    )
                    if self.strict_ocr_var.get() and self._is_suspicious_ocr(text_to_type):
                        self._set_status("OCR сомнительный: показал в поле, но не печатаю.")
                        if not repeat_ocr:
                            self._finish("OCR сомнительный: проверь текст в поле вручную.")
                            return
                        if not self._wait_ocr_interval(interval):
                            return
                        continue
                    else:
                        output_text = self._enter_after_each_word(text_to_type)
                        if type_mode == TYPE_MODE_PASTE:
                            self._paste_text_to_target(output_text)
                        else:
                            self._type_text_to_target(output_text, 60 / (max(1, wpm) * 5))

                        if not repeat_ocr:
                            self._finish(f"OCR считан и напечатан: {len(text_to_type)} символов.")
                            return
                    last_text = normalized

                if not repeat_ocr:
                    self._finish("OCR не нашёл новый текст.")
                    return
                if not self._wait_ocr_interval(interval):
                    return

            self._finish("Live OCR остановлен.")
        except Exception as exc:
            self._finish(f"Live OCR ошибка: {exc}")

    def _wait_ocr_interval(self, interval: float) -> bool:
        end_wait = time.monotonic() + interval
        while time.monotonic() < end_wait:
            if self._should_stop():
                self._finish("Live OCR остановлен.")
                return False
            time.sleep(0.05)
        return True

    def _capture_region_text(self, region: ScreenRegion, *, gray_only: bool = False) -> str:
        image_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                image_path = Path(temp_file.name)
            ImageGrab.grab(bbox=region.bbox).save(image_path)
            return self._cleanup_ocr_text(self._run_ocr_subprocess(image_path, timeout=30, gray_only=gray_only))
        finally:
            if image_path is not None:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _new_text_after_overlap(self, previous: str, current: str) -> str:
        previous_words = previous.split()
        current_words = current.split()
        if not current_words:
            return ""
        if current == previous:
            return ""

        max_overlap = min(len(previous_words), len(current_words))
        for size in range(max_overlap, 0, -1):
            if previous_words[-size:] == current_words[:size]:
                return " ".join(current_words[size:])

        if len(current_words) > len(previous_words) and current.startswith(previous):
            return current[len(previous):].strip()

        return current

    def _should_stop(self) -> bool:
        return self.stop_event.is_set() or self._is_key_down(VK_ESCAPE)

    def _is_key_down(self, vk_code: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk_code) & 0x8000)

    def _wait_for_key_release(self, vk_code: int) -> None:
        while self._is_key_down(vk_code) and not self.stop_event.is_set():
            time.sleep(0.03)

    def _finish(self, status: str) -> None:
        self.stop_event.set()
        self.after(0, lambda: self._finish_ui(status))

    def _finish_ui(self, status: str) -> None:
        self.deiconify()
        self._set_running_ui(False)
        self.status_var.set(status)

    def _set_running_ui(self, running: bool) -> None:
        if running:
            self.start_button.configure(state="disabled")
            self.live_button.configure(state="disabled")
            self.repeat_button.configure(state="disabled")
            self.select_region_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            return

        self.start_button.configure(state="normal")
        self.live_button.configure(state="normal")
        self.repeat_button.configure(state="normal")
        self.select_region_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _set_status(self, status: str) -> None:
        self.after(0, lambda: self.status_var.set(status))

    def _type_text_to_target(self, text: str, char_delay: float) -> None:
        typed = 0
        total = len(text)
        for char in text:
            if self._should_stop():
                raise RuntimeError(f"Остановлено. Напечатано {typed}/{total} символов.")

            self._send_char(char)
            typed += 1
            if typed % 10 == 0 or typed == total:
                self._set_status(f"Печатаю: {typed}/{total} символов.")
            time.sleep(char_delay)

    def _enter_after_each_word(self, text: str) -> str:
        words = text.split()
        if not words:
            return ""
        suffix = self._word_suffix()
        formatted_words = [f"{word}{suffix}" for word in words]
        if self.enter_after_word_var.get():
            result_parts: list[str] = []
            total_words = len(formatted_words)
            for index, (raw_word, formatted_word) in enumerate(zip(words, formatted_words), start=1):
                result_parts.append(formatted_word)
                if index == total_words:
                    if not self._no_enter_after_word(raw_word):
                        result_parts.append("\n")
                    continue
                if self._no_enter_after_word(raw_word):
                    result_parts.append(" ")
                elif self.enter_every_10_words_var.get() and index % 10 == 0:
                    result_parts.append("\n\n")
                else:
                    result_parts.append("\n")
            return "".join(result_parts)
        if self.enter_every_10_words_var.get():
            result_parts: list[str] = []
            total_words = len(formatted_words)
            for index, (raw_word, formatted_word) in enumerate(zip(words, formatted_words), start=1):
                result_parts.append(formatted_word)
                if index == total_words:
                    continue
                if index % 10 == 0 and not self._no_enter_after_word(raw_word):
                    result_parts.append("\n\n")
                else:
                    result_parts.append(" ")
            return "".join(result_parts).rstrip()
        return " ".join(formatted_words)

    def _format_repeat_word(self, word: str, position: int) -> str:
        formatted_word = f"{word}{self._word_suffix()}"
        if self.enter_every_10_words_var.get() and position % 10 == 0:
            return f"{formatted_word}\n\n"
        if self.enter_after_word_var.get() and not self._no_enter_after_word(word):
            return f"{formatted_word}\n"
        return f"{formatted_word} "

    def _no_enter_after_word(self, word: str) -> bool:
        cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", word).lower()
        return cleaned in {
            "а",
            "в",
            "и",
            "к",
            "о",
            "с",
            "у",
            "я",
            "бы",
            "во",
            "вы",
            "да",
            "до",
            "за",
            "из",
            "их",
            "ко",
            "ли",
            "мы",
            "на",
            "не",
            "но",
            "об",
            "он",
            "от",
            "по",
            "со",
            "то",
            "ты",
        }

    def _word_suffix(self) -> str:
        custom_tag = self.custom_tag_var.get().strip()
        if self.custom_tag_enabled_var.get() and custom_tag:
            tag = custom_tag if custom_tag.startswith("@") else f"@{custom_tag}"
            return f" - {tag}"
        return ""

    def _cleanup_ocr_text(self, text: str) -> str:
        if not self.russian_fix_var.get():
            return self._format_ocr_for_typing(text)
        if self._looks_like_latinized_russian(text):
            text = self._latinized_russian_to_cyrillic(text)
        return self._format_ocr_for_typing(text)

    def _format_ocr_for_typing(self, text: str) -> str:
        result = text.replace("\r", " ").replace("\n", " ")
        result = result.replace("_", " ").replace("|", " ")
        result = re.sub(r"[«»“”„`´]", "", result)
        result = re.sub(r"\s+", " ", result).strip()
        if self.lowercase_ocr_var.get():
            result = result.lower()
            result = self._apply_common_russian_ocr_fixes(result)
        if self.force_russian_var.get():
            result = self._force_russian_only(result)
        return result

    def _apply_common_russian_ocr_fixes(self, text: str) -> str:
        word_fixes = {
            "ьпрочэм": "впрочем",
            "ook": "бок",
            "xotb": "хоть",
            "xотb": "хоть",
            "xbatatb": "хватать",
            "obitb": "быть",
            "npuxoqutbch": "приходиться",
            "djimhhbin": "длинный",
            "xomutb": "ходить",
            "mykuk": "мужик",
            "myxkuk": "мужик",
            "huyto": "нужно",
            "nomhutb": "помнить",
            "dlosikhbin": "должный",
            "opocutb": "просить",
            "bxoqutb": "выходить",
            "6yato": "будто",
            "целыи": "целый",
            "русскии": "русский",
            "событйе": "событие",
            "приитй": "прийти",
            "прийтй": "прийти",
            "купийть": "купить",
            "одень": "очень",
            "неб0": "небо",
            "хознин": "хозяин",
            "cnywatb": "слушать",
            "cnywattb": "слушать",
            "tam": "там",
            "mo)kho": "можно",
        }

        def replace_word(match: re.Match[str]) -> str:
            word = match.group(0)
            return word_fixes.get(word, word)

        return re.sub(r"[A-Za-zА-Яа-яЁё0-9)]+", replace_word, text)

    def _force_russian_only(self, text: str) -> str:
        def convert_token(match: re.Match[str]) -> str:
            token = match.group(0)
            if not re.search(r"[A-Za-z]", token):
                return token
            return self._latin_token_to_russian(token)

        result = re.sub(r"[A-Za-z0-9)]+", convert_token, text)
        result = re.sub(r"[A-Za-z]", "", result)
        result = re.sub(r"\s+", " ", result).strip()
        return result

    def _latin_token_to_russian(self, token: str) -> str:
        word_fixes = {
            "ook": "бок",
            "xotb": "хоть",
            "xbatatb": "хватать",
            "obitb": "быть",
            "npuxoqutbch": "приходиться",
            "djimhhbin": "длинный",
            "xomutb": "ходить",
            "mykuk": "мужик",
            "myxkuk": "мужик",
            "huyto": "нужно",
            "nomhutb": "помнить",
            "dlosikhbin": "должный",
            "opocutb": "просить",
            "bxoqutb": "выходить",
            "6yato": "будто",
            "cnywatb": "слушать",
            "cnywattb": "слушать",
            "tam": "там",
            "mo)kho": "можно",
        }
        lowered = token.lower()
        if lowered in word_fixes:
            return word_fixes[lowered]

        letters = list(lowered)
        result: list[str] = []
        for index, char in enumerate(letters):
            prev_char = letters[index - 1] if index else ""
            next_char = letters[index + 1] if index + 1 < len(letters) else ""
            result.append(self._latin_ocr_char_to_russian(char, index, prev_char, next_char, len(letters)))
        return "".join(result)

    def _latin_ocr_char_to_russian(
        self,
        char: str,
        index: int,
        prev_char: str,
        next_char: str,
        token_length: int,
    ) -> str:
        if char == "6":
            return "б"
        if char == "0":
            return "о"
        if char == "1":
            return ""
        if char == "3":
            return "з"
        if char == "b":
            if index == token_length - 1:
                return "ь"
            if prev_char in {"x", "b"} or index == 0:
                return "в"
            return "ь"
        if char == "y":
            if prev_char in {"m", "h"}:
                return "у"
            if next_char in {"k", "t"}:
                return "у"
            return "у"
        if char == "u":
            return "и"
        if char == "j":
            return "л"
        if char == "q":
            return "д"
        if char == "w":
            return "ш"
        if char == "s":
            return "с"
        if char == "l":
            return "л"
        if char == "v":
            return "в"
        char_map = {
            "a": "а",
            "c": "с",
            "d": "д",
            "e": "е",
            "f": "ф",
            "g": "г",
            "h": "н",
            "i": "и",
            "k": "к",
            "m": "м",
            "n": "п",
            "o": "о",
            "p": "р",
            "r": "г",
            "t": "т",
            "x": "х",
            "z": "з",
        }
        return char_map.get(char, "")

    def _is_suspicious_ocr(self, text: str) -> bool:
        clean = text.strip()
        if len(clean) < 2:
            return True

        bad_chars = len(re.findall(r"[Јß•»\[\]\|_{}]", clean))
        words = re.findall(r"\S+", clean)
        noisy_words = 0
        for word in words:
            has_letters = bool(re.search(r"[A-Za-zА-Яа-яЁё]", word))
            has_noise = bool(re.search(r"[()<>\"'`~^=+*\\/]", word))
            has_digit_letter_mix = bool(re.search(r"\d", word)) and has_letters
            has_latin_cyrillic_mix = bool(re.search(r"[A-Za-z]", word)) and bool(
                re.search(r"[А-Яа-яЁё]", word)
            )
            if has_letters and (has_noise or has_digit_letter_mix or has_latin_cyrillic_mix):
                noisy_words += 1

        if bad_chars >= 1:
            return True
        if noisy_words >= 3:
            return True
        if words and noisy_words / len(words) >= 0.28:
            return True
        return False

    def _looks_like_latinized_russian(self, text: str) -> bool:
        cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        suspicious = len(re.findall(r"(?:[A-Za-z]*[013][A-Za-z]+|[A-Za-z]+[013][A-Za-z]*)", text))
        lookalike = sum(1 for char in text if char in "ABCEHKMOPTXYabcehkmnoprtxyVIU013")
        return latin >= 6 and cyrillic < latin and (lookalike >= latin * 0.55 or suspicious > 0)

    def _latinized_russian_to_cyrillic(self, text: str) -> str:
        replacements = [
            ("oVITY1", "ойти"),
            ("OVITY1", "ойти"),
            ("bIV1", "ый"),
            ("bI1", "ый"),
            ("bI", "ы"),
            ("V13", "из"),
            ("VI", "и"),
            ("V1", "й"),
            ("Y1", "и"),
            ("IY", "иу"),
        ]
        result = text
        for old, new in replacements:
            result = result.replace(old, new)
        result = re.sub(r"(?<!\d)3(?!\d)", "з", result)
        result = re.sub(r"(?<=[A-Za-zА-Яа-я])0|0(?=[A-Za-zА-Яа-я])", "о", result)

        char_map = str.maketrans(
            {
                "A": "а",
                "a": "а",
                "B": "в",
                "C": "с",
                "c": "с",
                "E": "е",
                "e": "е",
                "H": "н",
                "h": "н",
                "K": "к",
                "k": "к",
                "M": "м",
                "m": "м",
                "O": "о",
                "o": "о",
                "P": "р",
                "p": "р",
                "T": "т",
                "t": "т",
                "X": "х",
                "x": "х",
                "Y": "у",
                "y": "у",
                "n": "п",
                "r": "г",
                "g": "д",
                "Q": "ч",
                "q": "ч",
                "b": "ь",
                "V": "и",
                "I": "и",
                "U": "ш",
            }
        )
        result = result.translate(char_map)
        result = result.replace("іі", "и")
        result = result.replace("ій", "ий")
        result = result.replace("і", "и")
        return result

    def _send_char(self, char: str) -> None:
        if char == "\n":
            self._send_vk(VK_RETURN)
            return
        if char == "\t":
            self._send_vk(VK_TAB)
            return

        encoded = char.encode("utf-16-le")
        code_units = [
            encoded[index] | (encoded[index + 1] << 8)
            for index in range(0, len(encoded), 2)
        ]
        for code_unit in code_units:
            self._send_unicode(code_unit)

    def _send_unicode(self, code_unit: int) -> None:
        down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE, 0, 0)),
        )
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(
                ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
            ),
        )
        self._send_inputs(down, up)

    def _send_vk(self, vk_code: int) -> None:
        down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, 0, 0, 0)),
        )
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, KEYEVENTF_KEYUP, 0, 0)),
        )
        self._send_inputs(down, up)

    def _paste_text_to_target(self, text: str) -> None:
        previous_clipboard = None
        try:
            previous_clipboard = self.clipboard_get()
        except tk.TclError:
            pass

        event = threading.Event()

        def set_clipboard() -> None:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            event.set()

        self.after(0, set_clipboard)
        if not event.wait(timeout=3):
            raise RuntimeError("Не удалось записать текст в буфер обмена.")

        time.sleep(0.08)
        self._send_hotkey(VK_SHIFT, VK_INSERT)

        if previous_clipboard is not None:
            def restore_clipboard() -> None:
                try:
                    self.clipboard_clear()
                    self.clipboard_append(previous_clipboard)
                    self.update()
                except tk.TclError:
                    pass

            self.after(800, restore_clipboard)

    def _send_vk_down(self, vk_code: int) -> None:
        down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, 0, 0, 0)),
        )
        self._send_inputs(down)

    def _send_vk_up(self, vk_code: int) -> None:
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, KEYEVENTF_KEYUP, 0, 0)),
        )
        self._send_inputs(up)

    def _send_hotkey(self, modifier_vk: int, key_vk: int) -> None:
        modifier_down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(modifier_vk, 0, 0, 0, 0)),
        )
        key_down = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(key_vk, 0, 0, 0, 0)),
        )
        key_up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(key_vk, 0, KEYEVENTF_KEYUP, 0, 0)),
        )
        modifier_up = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(modifier_vk, 0, KEYEVENTF_KEYUP, 0, 0)),
        )
        self._send_inputs(modifier_down, key_down, key_up, modifier_up)

    def _send_inputs(self, *inputs: INPUT) -> None:
        input_array = (INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(input_array), input_array, ctypes.sizeof(INPUT))
        if sent != len(input_array):
            error_code = ctypes.get_last_error()
            raise RuntimeError(f"SendInput не отправил клавиши. Код Windows: {error_code}")

    def _close(self) -> None:
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    app = TextTyperApp()
    app.mainloop()
