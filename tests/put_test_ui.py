import tkinter as tk
from tkinter import ttk, messagebox
import time
import threading
from typing import Dict, Optional

from src.communication.plc_client import PLC_Client
from src.communication.plc_service import PLC_Service
from src.utils.logger import logger

logger = logger.bind(tag="put_test_ui")

PLC_HOST = "192.168.1.88"
PLC_PORT = 502
PLC_SLAVE_ID = 1
PLC_TIMEOUT = 5
STATION_ID = 1
POLL_INTERVAL_MS = 200


class PutTestApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("放货测试 - 工作站1")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.plc: Optional[PLC_Service] = None
        self.running = False
        self.putting = False

        self.slot_labels: Dict[str, tk.Label] = {}
        self.slot_status: Dict[str, str] = {}

        self._init_plc()
        self._build_ui()
        self._poll_loop()

    def _init_plc(self):
        client = PLC_Client(PLC_HOST, PLC_PORT, PLC_SLAVE_ID, PLC_TIMEOUT)
        self.plc = PLC_Service(client)
        self.plc.start_connects()
        self.plc.start_status_polling(interval=0.3)
        time.sleep(1)
        self.running = True

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(main_frame, text="工作站1 库位状态", font=("Microsoft YaHei", 14, "bold"))
        header.grid(row=0, column=0, columnspan=5, pady=(0, 10))

        pos_header_frame = ttk.Frame(main_frame)
        pos_header_frame.grid(row=1, column=0, columnspan=5, sticky="w", padx=5)
        for col, text in enumerate(["库位1(前左)", "库位2(前右)", "库位3(后左)", "库位4(后右)"], 1):
            ttk.Label(pos_header_frame, text=text, font=("Microsoft YaHei", 9, "bold")).grid(row=0, column=col, padx=8)

        for layer in range(1, 5):
            row_frame = ttk.Frame(main_frame)
            row_frame.grid(row=layer + 1, column=0, columnspan=5, pady=4, sticky="w")

            layer_label = ttk.Label(row_frame, text=f"第{layer}层", font=("Microsoft YaHei", 10), width=6)
            layer_label.pack(side=tk.LEFT, padx=(5, 5))

            for pos in range(1, 5):
                code = f"A{layer}{pos}"
                cell = tk.Label(
                    row_frame,
                    text="0",
                    width=6,
                    height=2,
                    font=("Microsoft YaHei", 12),
                    relief="groove",
                    bg="#e0e0e0",
                    fg="#333333",
                )
                cell.pack(side=tk.LEFT, padx=6)
                self.slot_labels[code] = cell
                self.slot_status[code] = "empty"

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=6, column=0, columnspan=5, pady=(15, 5))

        self.put_btn = ttk.Button(btn_frame, text="放货", command=self._on_put, width=12)
        self.put_btn.pack(side=tk.LEFT, padx=10)

        self.reset_btn = ttk.Button(btn_frame, text="清空库位", command=self._on_reset, width=12)
        self.reset_btn.pack(side=tk.LEFT, padx=10)

        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=("Microsoft YaHei", 9), foreground="gray")
        status_label.grid(row=7, column=0, columnspan=5, pady=(5, 0))

    def _on_put(self):
        dialog = PutConfigDialog(self.root)
        self.root.wait_window(dialog.top)
        if dialog.result is None:
            return

        config = dialog.result
        self.put_btn.config(state=tk.DISABLED)
        self.putting = True

        for layer in range(1, 5):
            total = sum(config.get(layer, {}).get(pos, 0) for pos in range(1, 5))
            if total == 0:
                for pos in range(1, 5):
                    code = f"A{layer}{pos}"
                    self.slot_labels[code].config(text="0", bg="#e0e0e0", fg="#333333")
                    self.slot_status[code] = "empty"
            else:
                for pos in range(1, 5):
                    code = f"A{layer}{pos}"
                    expected = config.get(layer, {}).get(pos, 0)
                    if expected > 0:
                        self.slot_labels[code].config(text=str(expected), bg="#fff3cd", fg="#856404")
                        self.slot_status[code] = "pending"
                    else:
                        self.slot_labels[code].config(text="0", bg="#e0e0e0", fg="#333333")
                        self.slot_status[code] = "empty"

        self.status_var.set("传送带已启动，等待光电确认...")

        thread = threading.Thread(target=self._execute_put, args=(config,), daemon=True)
        thread.start()

    def _execute_put(self, config: dict):
        station_id = STATION_ID

        for layer in range(1, 5):
            total = sum(config.get(layer, {}).get(pos, 0) for pos in range(1, 5))
            if total == 0:
                self.plc.command_cabinet_no_box(station_id, layer)

        self.plc.command_cabinet_place(station_id)

        self._confirm_and_update(config)

    def _confirm_and_update(self, config: dict):
        confirmed_layers = set()
        waiting_layers = set()

        for layer in range(1, 5):
            total = sum(config.get(layer, {}).get(pos, 0) for pos in range(1, 5))
            if total == 0:
                confirmed_layers.add(layer)
            else:
                waiting_layers.add(layer)

        base_front = {}
        for layer in waiting_layers:
            base_front[layer] = self.plc.is_photo_triggered(STATION_ID, layer, "front")

        max_wait = 120
        start = time.time()
        while len(confirmed_layers) < 4 and time.time() - start < max_wait:
            if not self.running:
                return
            time.sleep(0.2)
            for layer in list(waiting_layers):
                if layer in confirmed_layers:
                    continue
                front = self.plc.is_photo_triggered(STATION_ID, layer, "front")
                if front and not base_front[layer]:
                    self.root.after(0, self._update_layer_display, layer, config.get(layer, {}))
                    confirmed_layers.add(layer)

        self.root.after(0, self._on_put_done, config, confirmed_layers)

    def _update_layer_display(self, layer: int, layer_config: dict):
        for pos in range(1, 5):
            code = f"A{layer}{pos}"
            expected = layer_config.get(pos, 0)
            if expected > 0:
                self.slot_labels[code].config(text=str(expected), bg="#d4edda", fg="#155724")
                self.slot_status[code] = "confirmed"

    def _on_put_done(self, config: dict, confirmed_layers: set):
        for layer in range(1, 5):
            for pos in range(1, 5):
                code = f"A{layer}{pos}"
                expected = config.get(layer, {}).get(pos, 0)
                if expected > 0 and self.slot_status[code] == "pending":
                    self.slot_labels[code].config(text=f"{expected}?", bg="#f8d7da", fg="#721c24")
                    self.slot_status[code] = "mismatch"

        self.putting = False
        self.put_btn.config(state=tk.NORMAL)
        confirmed_count = sum(1 for l in confirmed_layers if sum(config.get(l, {}).get(p, 0) for p in range(1, 5)) > 0)
        total_layers = sum(1 for l in range(1, 5) if sum(config.get(l, {}).get(p, 0) for p in range(1, 5)) > 0)
        self.status_var.set(f"放货完成 - {confirmed_count}/{total_layers}层已确认")

    def _on_reset(self):
        for layer in range(1, 5):
            for pos in range(1, 5):
                code = f"A{layer}{pos}"
                self.slot_labels[code].config(text="0", bg="#e0e0e0", fg="#333333")
                self.slot_status[code] = "empty"

        if self.plc:
            self.plc.clear_all_cabinet_timeouts(STATION_ID)
        self.status_var.set("库位已清空，超时警报已清除")

    def _poll_loop(self):
        if not self.running:
            return
        self.root.after(POLL_INTERVAL_MS, self._poll_loop)

    def _on_close(self):
        self.running = False
        if self.plc:
            self.plc.close()
        self.root.destroy()


class PutConfigDialog:
    def __init__(self, parent: tk.Tk):
        self.result: Optional[Dict[int, Dict[int, int]]] = None
        self.spinboxes: Dict[str, ttk.Spinbox] = {}

        self.top = tk.Toplevel(parent)
        self.top.title("配置放货数量")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.top.transient(parent)

        frame = ttk.Frame(self.top, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="选择各层各库位放货数量 (0~4)", font=("Microsoft YaHei", 11, "bold")).grid(
            row=0, column=0, columnspan=5, pady=(0, 10)
        )

        for col, text in enumerate(["库位1", "库位2", "库位3", "库位4"], 1):
            ttk.Label(frame, text=text, font=("Microsoft YaHei", 9, "bold")).grid(row=1, column=col, padx=5)

        for layer in range(1, 5):
            ttk.Label(frame, text=f"第{layer}层", font=("Microsoft YaHei", 10)).grid(row=layer + 1, column=0, padx=(0, 10), pady=5)
            for pos in range(1, 5):
                key = f"A{layer}{pos}"
                spin = ttk.Spinbox(frame, from_=0, to=4, width=5, font=("Microsoft YaHei", 10))
                spin.set(0)
                spin.grid(row=layer + 1, column=pos, padx=5, pady=5)
                self.spinboxes[key] = spin

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=6, column=0, columnspan=5, pady=(15, 0))

        ttk.Button(btn_frame, text="确认", command=self._on_confirm, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self._on_cancel, width=10).pack(side=tk.LEFT, padx=10)

        self.top.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.top.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.top.winfo_height()) // 2
        self.top.geometry(f"+{x}+{y}")

    def _on_confirm(self):
        result: Dict[int, Dict[int, int]] = {}
        has_any = False
        for layer in range(1, 5):
            result[layer] = {}
            for pos in range(1, 5):
                key = f"A{layer}{pos}"
                val = int(self.spinboxes[key].get())
                result[layer][pos] = val
                if val > 0:
                    has_any = True

        if not has_any:
            messagebox.showwarning("提示", "请至少为一个库位设置放货数量", parent=self.top)
            return

        self.result = result
        self.top.destroy()

    def _on_cancel(self):
        self.top.destroy()


def main():
    root = tk.Tk()
    app = PutTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
