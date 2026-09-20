"""Small cross-platform GUI; OrcaSlicer configuration is only ever read."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from queue import Empty, Queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .engine import (
    ConversionError,
    available_plate_types,
    convert_project,
    default_plate_type,
)
from .profiles import (
    PrinterProfile,
    ProfileError,
    discover_config_dirs,
    list_accounts,
    load_printer_profiles,
)


AUTO_PLATE = "Auto — target printer default"
ACTIVE_ACCOUNT = "Auto — active Orca account"


class TransferApp:
    """Tk UI with all disk-intensive work dispatched off the event loop."""

    def __init__(self, root: tk.Tk, *, auto_discover: bool = True) -> None:
        self.root = root
        self.root.title("Orca Profile Transfer")
        self.root.minsize(790, 700)
        self.root.geometry("940x810")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self._destroyed = False
        self._drain_after_id: str | None = None
        self._initial_load_after_id: str | None = None
        self.events: Queue[tuple[str, object]] = Queue()
        self.busy = False
        self.close_when_done = False
        self.profiles: list[PrinterProfile] = []
        self.profile_labels: list[str] = []
        self.loaded_selection: tuple[str, str, str] | None = None
        self.output_path: Path | None = None
        self.controls: list[tuple[ttk.Widget, str]] = []
        self.source = tk.StringVar()
        self.config = tk.StringVar()
        self.resources = tk.StringVar()
        self.account = tk.StringVar(value=ACTIVE_ACCOUNT)
        self.printer = tk.StringVar()
        self.plate = tk.StringVar(value=AUTO_PLATE)
        self.output_dir = tk.StringVar()
        self.plate_hint = tk.StringVar(value="Load your saved printers to see plate options.")
        self.status = tk.StringVar(value="Choose an editable 3MF project and a saved printer.")
        self._build()
        self._drain_after_id = self.root.after(100, self._drain_events)
        if auto_discover:
            found = [str(path) for path in discover_config_dirs()]
            self.config_box.configure(values=found)
            if found:
                self.config.set(found[0])
                self._initial_load_after_id = self.root.after(150, self._load_profiles)

    def _register(self, widget: ttk.Widget, idle_state: str = "normal") -> ttk.Widget:
        self.controls.append((widget, idle_state))
        return widget

    def _build(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("TkDefaultFont", 20, "bold"))
        style.configure("Subtitle.TLabel", foreground="#536273")
        style.configure("Action.TButton", padding=(16, 9))
        frame = ttk.Frame(self.root, padding=(24, 18))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text="Orca Profile Transfer", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(frame, text="About / license", command=self._show_about).grid(row=0, column=0, sticky="e")
        ttk.Label(
            frame, text="A new copy of your project, prepared for your saved printer.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        source_frame = ttk.LabelFrame(frame, text="1  Project", padding=12)
        source_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        source_frame.columnconfigure(0, weight=1)
        self._register(ttk.Entry(source_frame, textvariable=self.source)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._register(ttk.Button(source_frame, text="Choose 3MF…", command=self._choose_source)).grid(row=0, column=1)
        ttk.Label(
            source_frame, text="Choose an editable project. The source file is never overwritten.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        target = ttk.LabelFrame(frame, text="2  Target printer", padding=12)
        target.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        target.columnconfigure(1, weight=1)
        ttk.Label(target, text="Orca configuration").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.config_box = ttk.Combobox(target, textvariable=self.config)
        self._register(self.config_box).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.config_box.bind("<<ComboboxSelected>>", lambda _event: self._load_profiles())
        self._register(ttk.Button(target, text="Browse…", command=self._choose_config)).grid(row=0, column=2, sticky="ew")
        ttk.Label(target, text="Resources (optional)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        self._register(ttk.Entry(target, textvariable=self.resources)).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
        self._register(ttk.Button(target, text="Browse…", command=self._choose_resources)).grid(row=1, column=2, sticky="ew", pady=(8, 0))
        ttk.Label(
            target, text="Usually detected automatically. Choose Orca's resources/profiles folder if a parent preset is missing.",
            style="Subtitle.TLabel", wraplength=790,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 8))
        ttk.Label(target, text="Local account").grid(row=3, column=0, sticky="w", padx=(0, 12))
        self.account_box = ttk.Combobox(target, textvariable=self.account, values=[ACTIVE_ACCOUNT], state="readonly")
        self._register(self.account_box, "readonly").grid(row=3, column=1, sticky="ew", padx=(0, 8))
        self.account_box.bind("<<ComboboxSelected>>", lambda _event: self._load_profiles())
        self._register(ttk.Button(target, text="Load printers", command=self._load_profiles)).grid(row=3, column=2, sticky="ew")
        ttk.Label(target, text="Saved printer").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        self.printer_box = ttk.Combobox(target, textvariable=self.printer, state="readonly")
        self._register(self.printer_box, "readonly").grid(row=4, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        self.printer_box.bind("<<ComboboxSelected>>", self._printer_changed)
        ttk.Label(target, text="Build plate").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=(8, 0))
        self.plate_box = ttk.Combobox(target, textvariable=self.plate, values=[AUTO_PLATE], state="readonly")
        self._register(self.plate_box, "readonly").grid(row=5, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(target, textvariable=self.plate_hint, style="Subtitle.TLabel", wraplength=790).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(6, 0),
        )

        output = ttk.LabelFrame(frame, text="3  Save a new copy", padding=12)
        output.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        output.columnconfigure(0, weight=1)
        self._register(ttk.Entry(output, textvariable=self.output_dir)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._register(ttk.Button(output, text="Choose folder…", command=self._choose_output)).grid(row=0, column=1)
        ttk.Label(
            output, text="Leave blank to save beside the source. Existing files are never replaced.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))
        actions = ttk.Frame(output)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(1, weight=1)
        self.convert_button = ttk.Button(actions, text="Create transferred copy", style="Action.TButton", command=self._convert)
        self._register(self.convert_button).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0))

        results = ttk.Frame(frame)
        results.grid(row=5, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)
        ttk.Label(results, textvariable=self.status, wraplength=820).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.result_text = tk.Text(results, height=5, wrap="word", relief="solid", borderwidth=1, padx=10, pady=8, state="disabled")
        self.result_text.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.result_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.result_text.configure(yscrollcommand=scrollbar.set)
        self.copy_button = ttk.Button(results, text="Copy output path", command=self._copy_path, state="disabled")
        self.copy_button.grid(row=2, column=0, sticky="e", pady=(6, 0))
        self._set_result(
            "This tool reads your saved printer profile and writes a new 3MF. "
            "It does not change Orca settings or send print jobs.\n\n"
            "After conversion: use File > Open in an already running OrcaSlicer. "
            "Starting Orca by opening a project can reset material selections in some versions. "
            "Verify the printer, each material, build plate, and sliced preview."
        )

    def _selection(self) -> tuple[str, str, str]:
        return (self.config.get().strip(), self.resources.get().strip(), self.account.get())

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Orca Profile Transfer",
            "Orca Profile Transfer\n"
            "Copyright © 2026 Orca Profile Transfer contributors\n\n"
            "Licensed under the GNU Affero General Public License, version 3 "
            "or (at your option) any later version. Redistribution and modification "
            "are permitted under that license. This software comes with NO WARRANTY.\n\n"
            "See LICENSE and THIRD_PARTY_NOTICES.md in the distribution. "
            "Corresponding source should accompany the release downloads.\n\n"
            "License: https://www.gnu.org/licenses/agpl-3.0.html\n\n"
            "This is an independent tool, not an official OrcaSlicer product.",
            parent=self.root,
        )

    def _choose_source(self) -> None:
        selected = filedialog.askopenfilename(parent=self.root, title="Choose an editable 3MF project", filetypes=[("3MF project", "*.3mf"), ("All files", "*")])
        if selected:
            self.source.set(selected)

    def _choose_config(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose OrcaSlicer configuration directory", mustexist=True)
        if selected:
            self.config.set(selected)
            self.account.set(ACTIVE_ACCOUNT)
            self._load_profiles()

    def _choose_resources(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose OrcaSlicer resources or profiles directory", mustexist=True)
        if selected:
            self.resources.set(selected)
            self._load_profiles()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose output directory", mustexist=True)
        if selected:
            self.output_dir.set(selected)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self.busy = busy
        for widget, idle_state in self.controls:
            widget.configure(state="disabled" if busy else idle_state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        if status:
            self.status.set(status)

    def _start(self, operation: str, callback: Callable[[], object], status: str) -> None:
        self._set_busy(True, status)

        def work() -> None:
            try:
                self.events.put((operation, callback()))
            except (ProfileError, ConversionError, OSError, ValueError) as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:
                # Do not include a settings dump or local traceback in the UI.
                self.events.put(("error", f"Unexpected {type(exc).__name__}. No successful output was reported. Check the project and profile, then try again."))

        threading.Thread(target=work, name=f"orca-transfer-{operation}", daemon=False).start()

    def _load_profiles(self) -> None:
        if self.busy:
            return
        config, resources, account = self._selection()
        if not config:
            messagebox.showinfo("Choose Orca configuration", "Choose the OrcaSlicer configuration directory first.", parent=self.root)
            return
        self.loaded_selection = None
        self.profiles = []
        self.printer.set("")
        self.printer_box.configure(values=[])
        self.plate.set(AUTO_PLATE)
        self.plate_box.configure(values=[AUTO_PLATE])
        self.plate_hint.set("Loading saved printer configuration…")

        def load() -> object:
            config_path = Path(config).expanduser()
            accounts = list_accounts(config_path)
            # Populate account choices even when choosing the active account fails.
            self.events.put(("accounts", accounts))
            profiles = list(load_printer_profiles(
                config_path,
                resources_dir=Path(resources).expanduser() if resources else None,
                account=None if account == ACTIVE_ACCOUNT else account,
            ))
            return profiles, (config, resources, account)

        self._start("profiles", load, "Reading saved printer profiles…")

    def _selected_profile(self) -> PrinterProfile | None:
        index = self.printer_box.current()
        if 0 <= index < len(self.profiles):
            return self.profiles[index]
        return None

    def _printer_changed(self, _event: object = None) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        choices = list(available_plate_types(profile))
        self.plate_box.configure(values=[AUTO_PLATE, *choices])
        self.plate.set(AUTO_PLATE)
        default = default_plate_type(profile)
        self.plate_hint.set(
            f"Target default: {default}. Select the plate actually fitted to your printer."
            if default else "This printer has no unambiguous plate default. Choose a build plate explicitly."
        )

    def _convert(self) -> None:
        if self.busy:
            return
        source = self.source.get().strip()
        profile = self._selected_profile()
        problem = None
        if not source:
            problem = "Choose an editable 3MF project first."
        elif not Path(source).expanduser().is_file():
            problem = "The selected source file does not exist. Choose an existing 3MF project."
        elif Path(source).suffix.lower() != ".3mf":
            problem = "Choose a .3mf project file."
        elif self.loaded_selection != self._selection():
            problem = "The configuration, resources, or account selection changed. Click Load printers before converting."
        elif profile is None:
            problem = "Load saved printer profiles and choose the target printer first."
        elif self.plate.get() == AUTO_PLATE and default_plate_type(profile) is None:
            problem = "The target printer has no unambiguous default plate. Select the plate fitted to your printer before converting."
        if problem:
            messagebox.showinfo("Ready to transfer?", problem, parent=self.root)
            return
        assert profile is not None
        output = self.output_dir.get().strip()
        plate = None if self.plate.get() == AUTO_PLATE else self.plate.get()
        self.output_path = None
        self.copy_button.configure(state="disabled")
        self._set_result("Checking the project and target printer. Large projects can take a little time.")
        self._start(
            "converted",
            lambda: convert_project(
                Path(source).expanduser(), profile,
                output_dir=Path(output).expanduser() if output else None,
                plate=plate,
            ),
            "Validating and creating a new project copy…",
        )

    def _drain_events(self) -> None:
        self._drain_after_id = None
        if self._destroyed:
            return
        try:
            while True:
                operation, payload = self.events.get_nowait()
                if operation == "accounts":
                    self.account_box.configure(values=[ACTIVE_ACCOUNT, *payload])
                    continue
                self._set_busy(False)
                if operation == "error":
                    self.status.set("Transfer could not continue.")
                    self._set_result(str(payload))
                    if not self.profiles:
                        self.plate_hint.set("Resolve the profile issue above, then load printers again.")
                    if not self.close_when_done:
                        messagebox.showerror("Cannot continue", str(payload), parent=self.root)
                elif operation == "profiles":
                    self.profiles, self.loaded_selection = payload
                    counts = Counter(profile.display_label for profile in self.profiles)
                    seen: Counter[str] = Counter()
                    self.profile_labels = []
                    for profile in self.profiles:
                        label = profile.display_label
                        if counts[label] > 1:
                            seen[label] += 1
                            label = f"{label} — {Path(profile.path).name} ({seen[profile.display_label]})"
                        self.profile_labels.append(label)
                    self.printer_box.configure(values=self.profile_labels)
                    if self.profiles:
                        self.printer_box.current(0)
                        self._printer_changed()
                        self.status.set(f"Loaded {len(self.profiles)} saved printer profile(s). Choose your target printer.")
                    else:
                        self.status.set("No saved printer profiles found.")
                        self._set_result("Save a printer preset in OrcaSlicer, then click Load printers. Check the configuration directory and local account if your printer is missing.")
                elif operation == "converted":
                    self.output_path = Path(payload.path)
                    self.copy_button.configure(state="normal")
                    details = [f"Created:\n{payload.path}", "The source file and Orca configuration were left unchanged."]
                    if payload.warnings:
                        details.append("Please review:\n" + "\n".join(f"• {warning}" for warning in payload.warnings))
                    details.append(
                        "Next: in an already running OrcaSlicer, choose File > Open and select this file. "
                        "Opening a project while starting Orca can reset material selections in some versions. "
                        "Check the selected printer, every material, plate, and sliced preview before printing."
                    )
                    self._set_result("\n\n".join(details))
                    self.status.set("Transferred copy created. Review the notes below before slicing.")
                if self.close_when_done:
                    self.root.destroy()
                    return
        except Empty:
            pass
        if not self._destroyed:
            self._drain_after_id = self.root.after(100, self._drain_events)

    def _on_destroy(self, event: tk.Event) -> None:
        """Cancel Tcl timers when closing normally or when a test destroys Tk."""
        if event.widget is not self.root:
            return
        self._destroyed = True
        for callback_id in (self._drain_after_id, self._initial_load_after_id):
            if callback_id is not None:
                try:
                    self.root.after_cancel(callback_id)
                except tk.TclError:
                    pass  # It may already have run or the interpreter may be closing.
        self._drain_after_id = None
        self._initial_load_after_id = None

    def _set_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _copy_path(self) -> None:
        if self.output_path is not None:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(self.output_path))
            self.status.set("Output path copied.")

    def _close(self) -> None:
        if self.busy:
            self.close_when_done = True
            self.status.set("Finishing the current operation before closing…")
        else:
            self.root.destroy()


def run_gui(*, smoke_test: bool = False) -> int:
    """Run the application; smoke mode constructs widgets without showing a window."""
    try:
        root = tk.Tk()
    except tk.TclError:
        print(
            "The graphical interface could not start. A desktop session and working "
            "Tcl/Tk installation are required. Use --cli for command-line conversion.",
            file=sys.stderr,
        )
        return 2
    if smoke_test:
        root.withdraw()
    TransferApp(root, auto_discover=not smoke_test)
    if smoke_test:
        root.update_idletasks()
        root.destroy()
        return 0
    root.mainloop()
    return 0


def main() -> int:
    """GUI console-script entry point."""
    return run_gui()
