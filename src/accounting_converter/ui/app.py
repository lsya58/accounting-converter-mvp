from __future__ import annotations

from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, ttk
except ModuleNotFoundError:
    tk = None
    filedialog = None
    ttk = None

from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import AppState, DiagnosticKind


class AccountingConverterApp:
    def __init__(self, root: object) -> None:
        if tk is None or ttk is None or filedialog is None:
            raise RuntimeError("tkinter is required to run the desktop GUI.")
        self.root = root
        self.controller = AccountingConverterController()
        self.profile_ids: list[str] = []

        self.root.title("会計データ変換ツール")
        self.root.geometry("760x520")

        self.profile_var = tk.StringVar()
        self.file_var = tk.StringVar(value="未選択")
        self.diagnostic_kind_var = tk.StringVar(value=DiagnosticKind.YAYOI.value)
        self.status_var = tk.StringVar(value="入力ファイルと変換設定を選択してください。")
        self.diagnostic_var = tk.StringVar(value="未実行")
        self.preflight_var = tk.StringVar(value="UNKNOWN")

        self._build()
        self._render(self.controller.load_profiles())

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        title = ttk.Label(main, text="会計データ変換ツール", font=("", 18, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        ttk.Label(main, text="Conversion Profile").grid(row=1, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(
            main,
            textvariable=self.profile_var,
            state="readonly",
        )
        self.profile_combo.grid(row=1, column=1, sticky="ew", padx=8)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(main, text="再読込", command=self._reload_profiles).grid(
            row=1,
            column=2,
            sticky="ew",
        )

        ttk.Label(main, text="入力ファイル").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Label(main, textvariable=self.file_var).grid(
            row=2,
            column=1,
            sticky="ew",
            padx=8,
            pady=(12, 0),
        )
        ttk.Button(main, text="選択", command=self._select_file).grid(
            row=2,
            column=2,
            sticky="ew",
            pady=(12, 0),
        )

        ttk.Label(main, text="診断対象").grid(row=3, column=0, sticky="w", pady=(12, 0))
        kind_frame = ttk.Frame(main)
        kind_frame.grid(row=3, column=1, sticky="w", padx=8, pady=(12, 0))
        ttk.Radiobutton(
            kind_frame,
            text="弥生候補",
            variable=self.diagnostic_kind_var,
            value=DiagnosticKind.YAYOI.value,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            kind_frame,
            text="JDL候補",
            variable=self.diagnostic_kind_var,
            value=DiagnosticKind.JDL.value,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Button(main, text="ファイルを確認", command=self._diagnose).grid(
            row=3,
            column=2,
            sticky="ew",
            pady=(12, 0),
        )

        ttk.Label(main, text="診断").grid(row=4, column=0, sticky="nw", pady=(16, 0))
        ttk.Label(main, textvariable=self.diagnostic_var, justify="left").grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(16, 0),
        )

        ttk.Label(main, text="Preflight").grid(row=5, column=0, sticky="w", pady=(16, 0))
        ttk.Label(main, textvariable=self.preflight_var).grid(
            row=5,
            column=1,
            sticky="ew",
            padx=8,
            pady=(16, 0),
        )
        ttk.Button(main, text="Preflight実行", command=self._preflight).grid(
            row=5,
            column=2,
            sticky="ew",
            pady=(16, 0),
        )

        ttk.Label(main, text="状態").grid(row=6, column=0, sticky="nw", pady=(16, 0))
        ttk.Label(main, textvariable=self.status_var, wraplength=520).grid(
            row=6,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(16, 0),
        )

        self.convert_button = ttk.Button(main, text="変換する", state="disabled")
        self.convert_button.grid(row=7, column=2, sticky="ew", pady=(24, 0))

    def _reload_profiles(self) -> None:
        self._render(self.controller.load_profiles())

    def _on_profile_selected(self, _event=None) -> None:
        index = self.profile_combo.current()
        profile_id = self.profile_ids[index] if 0 <= index < len(self.profile_ids) else None
        self._render(self.controller.select_profile(profile_id))

    def _select_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="入力ファイルを選択",
            filetypes=(("CSV/TXT", "*.csv *.txt"), ("All files", "*.*")),
        )
        if filename:
            self._render(self.controller.select_file(Path(filename)))

    def _diagnose(self) -> None:
        kind = DiagnosticKind(self.diagnostic_kind_var.get())
        self._render(self.controller.diagnose_selected(kind))

    def _preflight(self) -> None:
        self._render(self.controller.run_preflight())

    def _render(self, state: AppState) -> None:
        self.profile_ids = [profile.profile_id for profile in state.profiles]
        self.profile_combo["values"] = [profile.label for profile in state.profiles]
        if state.selected_profile_id in self.profile_ids:
            self.profile_combo.current(self.profile_ids.index(state.selected_profile_id))
        elif state.profiles:
            self.profile_combo.set("")
        else:
            self.profile_combo.set("保存済みProfileなし")

        self.file_var.set(state.selected_file.name if state.selected_file else "未選択")
        self.preflight_var.set(state.preflight_status)
        self.status_var.set(state.user_message)
        self.convert_button.configure(
            state="normal" if state.conversion_available else "disabled"
        )
        self.diagnostic_var.set(self._diagnostic_text(state))

    def _diagnostic_text(self, state: AppState) -> str:
        summary = state.diagnostic_summary
        if summary is None:
            return state.diagnostic_status.value
        diagnostics = (
            "未集計" if summary.diagnostic_count is None else str(summary.diagnostic_count)
        )
        records = (
            "未集計"
            if summary.data_record_count is None
            else str(summary.data_record_count)
        )
        return "\n".join(
            [
                f"形式候補: {summary.format_candidate}",
                f"データレコード数: {records}",
                f"診断メッセージ数: {diagnostics}",
                f"Error: {summary.error_count}",
                f"Warning: {summary.warning_count}",
                f"構造状態: {summary.structural_status}",
            ]
        )


def main() -> None:
    if tk is None:
        raise RuntimeError("tkinter is required to run the desktop GUI.")
    root = tk.Tk()
    AccountingConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
