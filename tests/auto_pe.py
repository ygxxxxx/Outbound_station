import tkinter as tk
from tkinter import ttk
import threading
import time

from src.communication.plc_client import PLC_Client
from src.communication.plc_registers import StatusAddr
from src.utils.logger import logger

logger = logger.bind(tag="auto_photoelectric")

COMPLETE_FLAG_REG = 64
PHOTO_COUNT_REG = 65
GRIPPER_STATUS_START = StatusAddr.GRIPPER_STATUS_START
GRIPPER_STATUS_COUNT = StatusAddr.GRIPPER_STATUS_COUNT


class AutoPeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("出库流水线光电计数模拟")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.plc = PLC_Client(host="192.168.1.88", port=502, slave_id=1)
        self.running = False
        self.skip_event = threading.Event()

        self._build_ui()
        threading.Thread(target=self._connect, daemon=True).start()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="出库流水线光电计数模拟", font=("Microsoft YaHei", 14, "bold")).grid(
            row=0, column=0, columnspan=3, pady=(0, 15)
        )

        ttk.Label(main_frame, text="自动写入间隔(秒):", font=("Microsoft YaHei", 10)).grid(
            row=1, column=0, sticky="w", pady=5
        )
        self.interval_var = tk.StringVar(value="10")
        self.interval_entry = ttk.Entry(main_frame, textvariable=self.interval_var, width=8, font=("Microsoft YaHei", 10))
        self.interval_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(main_frame, text="自动写入计数值:", font=("Microsoft YaHei", 10)).grid(
            row=2, column=0, sticky="w", pady=5
        )
        self.auto_count_var = tk.StringVar(value="2")
        self.auto_count_entry = ttk.Entry(main_frame, textvariable=self.auto_count_var, width=8, font=("Microsoft YaHei", 10))
        self.auto_count_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(main_frame, text="手动写入计数值:", font=("Microsoft YaHei", 10)).grid(
            row=3, column=0, sticky="w", pady=5
        )
        self.manual_count_var = tk.StringVar(value="2")
        self.manual_count_entry = ttk.Entry(main_frame, textvariable=self.manual_count_var, width=8, font=("Microsoft YaHei", 10))
        self.manual_count_entry.grid(row=3, column=1, padx=5, pady=5)

        self.manual_btn = ttk.Button(main_frame, text="手动写入", command=self._on_manual, width=12)
        self.manual_btn.grid(row=3, column=2, padx=5, pady=5)

        self.start_btn = ttk.Button(main_frame, text="启动", command=self._on_start, width=12)
        self.start_btn.grid(row=4, column=0, pady=(15, 5))

        self.stop_btn = ttk.Button(main_frame, text="停止", command=self._on_stop, width=12, state=tk.DISABLED)
        self.stop_btn.grid(row=4, column=1, pady=(15, 5))

        self.status_var = tk.StringVar(value="正在连接PLC...")
        ttk.Label(main_frame, textvariable=self.status_var, font=("Microsoft YaHei", 9), foreground="gray").grid(
            row=5, column=0, columnspan=3, pady=(10, 0)
        )

        self.gripper_var = tk.StringVar(value="")
        self.gripper_label = ttk.Label(main_frame, textvariable=self.gripper_var, font=("Microsoft YaHei", 9), foreground="blue")
        self.gripper_label.grid(row=6, column=0, columnspan=3, pady=(3, 0))

        self.log_var = tk.StringVar(value="")
        self.log_label = ttk.Label(main_frame, textvariable=self.log_var, font=("Microsoft YaHei", 9), foreground="green")
        self.log_label.grid(row=7, column=0, columnspan=3, pady=(5, 0))

    def _connect(self):
        try:
            self.plc._ensure_connection()
            self.root.after(0, lambda: self.status_var.set("已连接"))
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"连接失败: {e}"))

    def _any_gripper_running(self) -> bool:
        result = self.plc.read_holding_registers(GRIPPER_STATUS_START, GRIPPER_STATUS_COUNT)
        running = [i + 1 for i, v in enumerate(result) if v == 1]
        if running:
            self.root.after(0, lambda: self.gripper_var.set(f"夹爪运行中: {running}"))
        else:
            self.root.after(0, lambda: self.gripper_var.set("所有夹爪空闲"))
        return len(running) > 0

    def _write_count(self, count: int):
        if not self._any_gripper_running():
            self.log_var.set("夹爪未运行，不允许写入光电计数")
            logger.warning("夹爪未运行，跳过写入光电计数")
            return
        flag = self.plc.read_holding_registers(COMPLETE_FLAG_REG, 1)[0]
        if flag == 1:
            self.log_var.set("出库完成标志为1，上位机即将清零，跳过写入")
            logger.info("出库完成标志为1，跳过写入光电计数，等待上位机清零")
            return
        self.plc.write_holding_registers(PHOTO_COUNT_REG, [count])
        msg = f"已写入光电计数 = {count}"
        logger.info(msg)
        self.log_var.set(msg)

    def _on_manual(self):
        try:
            count = int(self.manual_count_var.get())
        except ValueError:
            self.log_var.set("计数值无效")
            return
        try:
            self._write_count(count)
            self.skip_event.set()
        except Exception as e:
            self.log_var.set(f"写入失败: {e}")

    def _on_start(self):
        if self.running:
            return
        self.running = True
        self.skip_event.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("运行中")
        t = threading.Thread(target=self._auto_loop, daemon=True)
        t.start()

    def _on_stop(self):
        self.running = False
        self.skip_event.set()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("已停止")

    def _auto_loop(self):
        while self.running:
            try:
                interval = float(self.interval_var.get())
            except ValueError:
                interval = 10.0
            try:
                auto_count = int(self.auto_count_var.get())
            except ValueError:
                auto_count = 2

            self.skip_event.clear()
            if self.skip_event.wait(timeout=interval):
                pass
            else:
                if self.running:
                    try:
                        self.root.after(0, self._write_count, auto_count)
                    except Exception:
                        pass

    def _on_close(self):
        self.running = False
        self.skip_event.set()
        try:
            self.plc.plc_close()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = AutoPeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
