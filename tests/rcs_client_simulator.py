import tkinter as tk
from tkinter import ttk, messagebox
from src.communication.rcs_sever_protocol import decode, encode
from src.utils.logger import logger

import socket
import time
import random
from datetime import datetime
import threading
import copy
import json
from collections import Counter
from pathlib import Path

logger = logger.bind(tag='rcs_client_simulator')


# ── Constants ───────────────────────────────────────────────────────

STATION_IDS = ("A", "B", "C")
LOGISTICS_OPTIONS = ("shunfeng", "yunda", "zhongtong", "yuantong", "jd", "ems")
MANUAL_PROCESS_OPTIONS = ("N", "G", "S")
PACKAGING_LINE_OPTIONS = ("HS1", "HS2", "MP1", "MA1", "MO1")
BOX_TYPE_OPTIONS = ("DW01-A", "DW01-B", "DW02-A", "DW02-B")
GENERATED_OUTBOUND_FILE = Path(__file__).with_name("generated_outbound_tasks.json")
SIMULATOR_HISTORY_FILE = Path(__file__).with_name("simulator_history.json")


# ── RCS Simulator Backend ──────────────────────────────────────────

class RCS_Simulator:
    def __init__(self, host: str, status_port: int = 23310, task_port: int = 23311):
        self.host = host
        self.status_port = status_port
        self.task_port = task_port
        self.status_sock = None
        self.task_sock = None

    def connect(self):
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.status_sock.connect((self.host, self.status_port))
        self.task_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.task_sock.connect((self.host, self.task_port))

    def send_request(self, sock: socket.socket, cmd: int, body_dict: dict = None) -> dict:
        seq = random.randint(0, 65535)
        data = encode(seq, cmd, body_dict)
        sock.sendall(data)
        recv_buffer = b''
        while True:
            data = sock.recv(4096)
            if not data:
                raise ConnectionError("连接断开")
            recv_buffer += data
            result, recv_buffer = decode(recv_buffer)
            if result is not None:
                _, _, body = result
                return body

    def query_outbound_task_detail(self) -> dict:
        return self.send_request(self.status_sock, 1000)

    def query_outbound_storage(self) -> dict:
        return self.send_request(self.status_sock, 1001)

    def query_outbound_status(self) -> dict:
        return self.send_request(self.status_sock, 1002)

    def query_plc_status(self) -> dict:
        return self.send_request(self.status_sock, 1003)

    def query_inbound_status(self) -> dict:
        return self.send_request(self.status_sock, 1005)

    def query_outbound_subdevice(self) -> dict:
        return self.send_request(self.status_sock, 1006)

    def query_outbound_batch(self) -> dict:
        return self.send_request(self.status_sock, 1100)

    def dispatch_outbound_task(self, task_data: dict) -> dict:
        return self.send_request(self.task_sock, 2000, task_data)

    def dispatch_inbound_route(self, route_data: dict) -> dict:
        return self.send_request(self.task_sock, 2001, route_data)

    def notify_clear_station_abnormal(self, station_id: str) -> dict:
        return self.send_request(self.task_sock, 2003, {"station_id": station_id, "timestamp": int(time.time() * 1000)})

    def close(self) -> None:
        if self.status_sock:
            self.status_sock.close()
        if self.task_sock:
            self.task_sock.close()


# ── GUI Application ────────────────────────────────────────────────

class SimulatorApp:

    def __init__(self):
        self.simulator: RCS_Simulator | None = None
        self.connected = False
        self._last_put_task: dict | None = None
        self._last_out_task: dict | None = None
        self._history_data: list[dict] = []

        self.root = tk.Tk()
        self.root.title("RCS 客户端模拟器")
        self.root.geometry("1280x960")
        self.root.minsize(1060, 800)

        self._build_connection_panel()
        self._build_notebook()
        self._build_response_panel()
        self._build_status_bar()

        self._load_history()
        self._set_connected(False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self):
        self.root.mainloop()

    # ────────────── Connection Panel ──────────────

    def _build_connection_panel(self):
        frame = ttk.LabelFrame(self.root, text="连接设置", padding=8)
        frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(frame, text="主机:").pack(side=tk.LEFT, padx=(0, 4))
        self.host_var = tk.StringVar(value="192.168.2.202")
        ttk.Entry(frame, textvariable=self.host_var, width=14).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(frame, text="状态端口:").pack(side=tk.LEFT, padx=(0, 4))
        self.sp_var = tk.IntVar(value=23310)
        ttk.Entry(frame, textvariable=self.sp_var, width=7).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(frame, text="任务端口:").pack(side=tk.LEFT, padx=(0, 4))
        self.tp_var = tk.IntVar(value=23311)
        ttk.Entry(frame, textvariable=self.tp_var, width=7).pack(side=tk.LEFT, padx=(0, 14))

        self.conn_btn = ttk.Button(frame, text="连接", command=self._toggle_connection, width=8)
        self.conn_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.conn_label = ttk.Label(frame, text="未连接", foreground="red", font=("", 10, "bold"))
        self.conn_label.pack(side=tk.LEFT)

    def _toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        try:
            self.simulator = RCS_Simulator(
                self.host_var.get(),
                self.sp_var.get(),
                self.tp_var.get(),
            )
            self.simulator.connect()
            self.connected = True
            self._set_connected(True)
            self._log("已连接到上位机")
        except Exception as e:
            messagebox.showerror("连接失败", str(e))

    def _disconnect(self):
        if self.simulator:
            try:
                self.simulator.close()
            except Exception:
                pass
        self.connected = False
        self.simulator = None
        self._set_connected(False)
        self._log("已断开连接")

    def _set_connected(self, val: bool):
        self.conn_btn.config(text="断开" if val else "连接")
        self.conn_label.config(
            text="已连接" if val else "未连接",
            foreground="green" if val else "red",
        )

    def _require_connection(self) -> bool:
        if not self.connected or not self.simulator:
            messagebox.showwarning("提示", "请先连接上位机")
            return False
        return True

    # ────────────── Notebook ──────────────

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self._build_query_tab()
        self._build_putaway_tab()
        self._build_outbound_tab()
        self._build_clear_abnormal_tab()
        self._build_history_tab()

    # ──── Query Tab ────

    def _build_query_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  状态查询  ")

        queries = [
            ("查询出库任务执行情况", self._q_task_detail),
            ("查询出库库位信息",     self._q_storage),
            ("查询出库工作站状态",   self._q_status),
            ("查询PLC状态",          self._q_plc),
            ("批量查询全部信息",     self._q_batch),
            ("查询入库状态",         self._q_inbound),
            ("查询出库子设备",       self._q_subdevice),
            ("解除传送带超时报警",   self._q_clear_timeout),
        ]

        for i, (text, cmd) in enumerate(queries):
            btn = ttk.Button(tab, text=text, command=cmd, width=24)
            btn.grid(row=i // 3, column=i % 3, padx=10, pady=8, sticky=tk.EW)

        for i in range(3):
            tab.columnconfigure(i, weight=1)

    # ──── Putaway Tab ────

    def _build_putaway_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="  放货任务  ")

        # -- basic info --
        row0 = ttk.Frame(tab)
        row0.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(row0, text="任务ID:").pack(side=tk.LEFT, padx=(0, 4))
        self.put_tid = tk.StringVar(value=f"PUT_{int(time.time())}")
        ttk.Entry(row0, textvariable=self.put_tid, width=22).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row0, text="刷新", width=4,
                   command=lambda: self.put_tid.set(f"PUT_{int(time.time())}")).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row0, text="工作站:").pack(side=tk.LEFT, padx=(0, 4))
        self.put_station = tk.StringVar(value="A")
        cb_station = ttk.Combobox(row0, textvariable=self.put_station,
                                  values=list(STATION_IDS), width=4, state="readonly")
        cb_station.pack(side=tk.LEFT, padx=(0, 20))
        cb_station.bind("<<ComboboxSelected>>", lambda _: self._refresh_location_combo())

        # -- quick fill --
        qf = ttk.LabelFrame(tab, text="快速填货", padding=6)
        qf.pack(fill=tk.X, pady=4)

        ttk.Label(qf, text="SKU:").grid(row=0, column=0, padx=4, sticky=tk.W)
        self.put_sku = tk.StringVar(value="SKU1")
        ttk.Entry(qf, textvariable=self.put_sku, width=12).grid(row=0, column=1, padx=4)

        ttk.Label(qf, text="每格数量:").grid(row=0, column=2, padx=4)
        self.put_qty = tk.IntVar(value=4)
        ttk.Spinbox(qf, from_=1, to=4, textvariable=self.put_qty, width=4).grid(row=0, column=3, padx=4)

        ttk.Button(qf, text="填满全部库位(16格)", command=self._put_fill_all).grid(row=0, column=4, padx=8)
        ttk.Button(qf, text="随机生成约20件", command=self._put_generate_random).grid(row=0, column=5, padx=8)

        ttk.Label(qf, text="指定层:").grid(row=0, column=6, padx=4)
        self.put_layer = tk.IntVar(value=1)
        ttk.Spinbox(qf, from_=1, to=4, textvariable=self.put_layer, width=4).grid(row=0, column=7, padx=4)

        ttk.Button(qf, text="填满指定层(4格)", command=self._put_fill_layer).grid(row=0, column=8, padx=8)

        ma = ttk.LabelFrame(tab, text="添加单个库位", padding=6)
        ma.pack(fill=tk.X, pady=4)

        ttk.Label(ma, text="库位:").pack(side=tk.LEFT, padx=4)
        self.put_loc = tk.StringVar()
        self.put_loc_combo = ttk.Combobox(ma, textvariable=self.put_loc, width=6)
        self.put_loc_combo.pack(side=tk.LEFT, padx=4)
        self._refresh_location_combo()

        ttk.Label(ma, text="SKU:").pack(side=tk.LEFT, padx=4)
        self.put_loc_sku = tk.StringVar(value="SKU1")
        ttk.Entry(ma, textvariable=self.put_loc_sku, width=12).pack(side=tk.LEFT, padx=4)

        ttk.Label(ma, text="x").pack(side=tk.LEFT, padx=2)
        self.put_loc_qty = tk.IntVar(value=4)
        ttk.Spinbox(ma, from_=1, to=4, textvariable=self.put_loc_qty, width=3).pack(side=tk.LEFT, padx=2)
        ttk.Label(ma, text="件").pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(ma, text="添加", command=self._put_add_manual).pack(side=tk.LEFT, padx=8)

        # -- treeview --
        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        cols = ("location", "sku", "count")
        self.put_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        self.put_tree.heading("location", text="库位")
        self.put_tree.heading("sku", text="SKU")
        self.put_tree.heading("count", text="数量")
        self.put_tree.column("location", width=80, anchor=tk.CENTER)
        self.put_tree.column("sku", width=400)
        self.put_tree.column("count", width=60, anchor=tk.CENTER)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.put_tree.yview)
        self.put_tree.configure(yscrollcommand=sb.set)
        self.put_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = ttk.Frame(tab)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="删除选中", command=self._put_del_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="清空列表", command=self._put_clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="重复上次放货任务", command=self._put_repeat_last).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="下发放货任务", command=self._put_send).pack(side=tk.RIGHT, padx=4)

    # ──── Outbound Tab ────

    def _build_outbound_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="  出库任务  ")

        # -- basic info --
        row0 = ttk.Frame(tab)
        row0.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(row0, text="任务ID:").pack(side=tk.LEFT, padx=(0, 4))
        self.out_tid = tk.StringVar(value=f"OUT_{int(time.time())}")
        ttk.Entry(row0, textvariable=self.out_tid, width=22).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row0, text="刷新", width=4,
                   command=lambda: self.out_tid.set(f"OUT_{int(time.time())}")).pack(side=tk.LEFT)

        # -- default settings --
        ds = ttk.LabelFrame(tab, text="默认包裹设置 (新增包裹自动填充)", padding=6)
        ds.pack(fill=tk.X, pady=4)

        self.out_box = tk.StringVar(value=BOX_TYPE_OPTIONS[0])
        self.out_logi = tk.StringVar(value=LOGISTICS_OPTIONS[0])
        self.out_manual = tk.StringVar(value=MANUAL_PROCESS_OPTIONS[0])
        self.out_pline = tk.StringVar(value=PACKAGING_LINE_OPTIONS[0])

        settings = [
            ("纸箱类型:", self.out_box, BOX_TYPE_OPTIONS),
            ("物流:", self.out_logi, LOGISTICS_OPTIONS),
            ("人工处理:", self.out_manual, MANUAL_PROCESS_OPTIONS),
            ("打包线:", self.out_pline, PACKAGING_LINE_OPTIONS),
        ]
        for i, (label, var, opts) in enumerate(settings):
            ttk.Label(ds, text=label).grid(row=i // 2, column=(i % 2) * 2, padx=4, pady=2, sticky=tk.W)
            ttk.Combobox(ds, textvariable=var, values=list(opts),
                         width=12, state="readonly").grid(row=i // 2, column=(i % 2) * 2 + 1, padx=4, pady=2)

        # -- quick add --
        qa = ttk.LabelFrame(tab, text="快速添加包裹", padding=6)
        qa.pack(fill=tk.X, pady=4)

        ttk.Label(qa, text="包裹ID:").grid(row=0, column=0, padx=4)
        self.out_pkg_id = tk.StringVar()
        ttk.Entry(qa, textvariable=self.out_pkg_id, width=12).grid(row=0, column=1, padx=4)

        ttk.Label(qa, text="面单:").grid(row=0, column=2, padx=4)
        self.out_face = tk.StringVar(value="FS1")
        ttk.Entry(qa, textvariable=self.out_face, width=8).grid(row=0, column=3, padx=4)

        ttk.Label(qa, text="货物SKU(逗号分隔):").grid(row=0, column=4, padx=4)
        self.out_goods_default = tk.StringVar(value="SKU1,SKU2")
        ttk.Entry(qa, textvariable=self.out_goods_default, width=18).grid(row=0, column=5, padx=4)

        ttk.Button(qa, text="添加", command=self._out_add_one).grid(row=0, column=6, padx=8)

        ttk.Label(qa, text="批量添加:").grid(row=1, column=0, padx=4, pady=6)
        self.out_batch_n = tk.IntVar(value=3)
        ttk.Spinbox(qa, from_=1, to=50, textvariable=self.out_batch_n, width=4).grid(row=1, column=1, padx=4, pady=6)
        ttk.Label(qa, text="个包裹 (ID自动编号)").grid(row=1, column=2, columnspan=3, padx=4, pady=6, sticky=tk.W)
        ttk.Button(qa, text="批量添加", command=self._out_add_batch).grid(row=1, column=5, columnspan=2, padx=8, pady=6)

        # -- treeview --
        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        cols = ("pid", "box", "face", "logi", "manual", "pline", "goods")
        self.out_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        hdr = {"pid": "包裹ID", "box": "纸箱", "face": "面单",
               "logi": "物流", "manual": "人工", "pline": "打包线", "goods": "货物SKU"}
        w = {"pid": 80, "box": 75, "face": 55, "logi": 70, "manual": 50, "pline": 60, "goods": 240}
        for c in cols:
            self.out_tree.heading(c, text=hdr[c])
            self.out_tree.column(c, width=w[c], anchor=tk.W if c == "goods" else tk.CENTER)

        sb2 = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.out_tree.yview)
        self.out_tree.configure(yscrollcommand=sb2.set)
        self.out_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = ttk.Frame(tab)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="删除选中", command=self._out_del_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="清空列表", command=self._out_clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="重复上次出库任务", command=self._out_repeat_last).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="随机生成(A站)", command=self._out_generate_station_a).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="随机生成(全站清空)", command=self._out_generate_all_stations).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="下发出库任务", command=self._out_send).pack(side=tk.RIGHT, padx=4)

    # ────────────── Response Panel ──────────────

    def _build_clear_abnormal_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  异常解除  ")

        # ── Clear Timeout ──
        timeout_frame = ttk.LabelFrame(tab, text="解除传送带超时报警 (2001)", padding=10)
        timeout_frame.pack(fill=tk.X, pady=6)

        ttk.Button(timeout_frame, text="解除所有工作站传送带超时", command=self._q_clear_timeout,
                   width=28).pack(pady=4)

        # ── Clear Station Abnormal ──
        clear_abnormal_frame = ttk.LabelFrame(tab, text="解除工作站异常状态 (2003)", padding=10)
        clear_abnormal_frame.pack(fill=tk.X, pady=6)

        r1 = ttk.Frame(clear_abnormal_frame)
        r1.pack(fill=tk.X, pady=4)

        ttk.Label(r1, text="工作站:").pack(side=tk.LEFT, padx=(0, 4))
        self.clear_abnormal_station_var = tk.StringVar(value="A")
        ttk.Combobox(r1, textvariable=self.clear_abnormal_station_var,
                     values=list(STATION_IDS), width=4, state="readonly").pack(side=tk.LEFT, padx=(0, 20))

        ttk.Button(r1, text="解除异常状态", command=self._t_clear_abnormal, width=14).pack(side=tk.LEFT, padx=4)

        r2 = ttk.Frame(clear_abnormal_frame)
        r2.pack(fill=tk.X, pady=4)

        ttk.Label(r2, text="快捷:").pack(side=tk.LEFT, padx=(0, 8))
        for station in STATION_IDS:
            ttk.Button(r2, text=f"解除{station}站异常",
                       command=lambda s=station: self._clear_abnormal_quick(s),
                       width=12).pack(side=tk.LEFT, padx=4)

    # ────────────── Response Panel ──────────────

    def _build_response_panel(self):
        frame = ttk.LabelFrame(self.root, text="响应结果", padding=4)
        frame.pack(fill=tk.BOTH, padx=10, pady=(0, 4))

        top = ttk.Frame(frame)
        top.pack(fill=tk.X)
        ttk.Label(top, text="").pack(side=tk.LEFT)
        ttk.Button(top, text="清空", command=self._clear_response, width=5).pack(side=tk.RIGHT)

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.resp_text = tk.Text(text_frame, height=18, wrap=tk.WORD, state=tk.DISABLED,
                                 font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        sb = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.resp_text.yview)
        self.resp_text.configure(yscrollcommand=sb.set)
        self.resp_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_status_bar(self):
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)).pack(fill=tk.X, padx=10, pady=(0, 6))

    # ────────────── Helpers ──────────────

    def _log(self, msg: str):
        self.resp_text.config(state=tk.NORMAL)
        self.resp_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.resp_text.see(tk.END)
        self.resp_text.config(state=tk.DISABLED)

    def _log_response(self, label: str, resp: dict):
        self.resp_text.config(state=tk.NORMAL)
        self.resp_text.insert(tk.END, f"\n{'=' * 55}\n  {label}\n{'=' * 55}\n")
        self._format_dict(resp, 0)
        self.resp_text.insert(tk.END, f"{'=' * 55}\n\n")
        self.resp_text.see(tk.END)
        self.resp_text.config(state=tk.DISABLED)

    def _format_dict(self, obj, indent: int):
        prefix = "  " * indent
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list):
                    self.resp_text.insert(tk.END, f"{prefix}{k}:\n")
                    if not v:
                        self.resp_text.insert(tk.END, f"{prefix}  (空)\n")
                    elif isinstance(v[0], dict):
                        for i, item in enumerate(v):
                            self.resp_text.insert(tk.END, f"{prefix}  [{i}]\n")
                            self._format_dict(item, indent + 2)
                    else:
                        for item in v:
                            self.resp_text.insert(tk.END, f"{prefix}  - {item}\n")
                elif isinstance(v, dict):
                    self.resp_text.insert(tk.END, f"{prefix}{k}:\n")
                    self._format_dict(v, indent + 1)
                else:
                    self.resp_text.insert(tk.END, f"{prefix}{k}: {v}\n")
        else:
            self.resp_text.insert(tk.END, f"{prefix}{obj}\n")

    def _clear_response(self):
        self.resp_text.config(state=tk.NORMAL)
        self.resp_text.delete("1.0", tk.END)
        self.resp_text.config(state=tk.DISABLED)

    def _run_in_thread(self, func):
        def wrapper():
            try:
                func()
            except ConnectionError as e:
                self.root.after(0, lambda: self._handle_disconnect(str(e)))
            except Exception as e:
                self.root.after(0, lambda: self._log(f"操作失败: {e}"))

        threading.Thread(target=wrapper, daemon=True).start()

    def _handle_disconnect(self, msg: str):
        self._log(f"连接断开: {msg}")
        self._disconnect()

    # ────────────── Query Actions ──────────────

    def _q_task_detail(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("出库任务执行情况", self.simulator.query_outbound_task_detail))

    def _q_storage(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("出库库位信息", self.simulator.query_outbound_storage))

    def _q_status(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("出库工作站状态", self.simulator.query_outbound_status))

    def _q_plc(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("PLC状态", self.simulator.query_plc_status))

    def _q_batch(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("批量查询全部信息", self.simulator.query_outbound_batch))

    def _q_inbound(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("入库状态", self.simulator.query_inbound_status))

    def _q_subdevice(self):
        if not self._require_connection():
            return
        self._run_in_thread(lambda: self._do_query("出库子设备", self.simulator.query_outbound_subdevice))

    def _q_clear_timeout(self):
        if not self._require_connection():
            return

        def do():
            data = {"clear_conveyor_timeout": 1, "timestamp": int(time.time() * 1000)}
            resp = self.simulator.dispatch_inbound_route(data)
            self.root.after(0, lambda: self._log_response("解除传送带超时报警", resp))
            self._add_history_record({
                "type": "query",
                "timestamp": int(time.time() * 1000),
                "task_id": "",
                "summary": "解除传送带超时报警",
                "data": resp,
            })

        self._run_in_thread(do)

    def _do_query(self, label: str, query_fn):
        resp = query_fn()
        self.root.after(0, lambda: self._log_response(label, resp))
        self._add_history_record({
            "type": "query",
            "timestamp": int(time.time() * 1000),
            "task_id": "",
            "summary": label,
            "data": resp,
        })

    def _t_clear_abnormal(self):
        station = self.clear_abnormal_station_var.get()
        self._send_clear_abnormal(station)

    def _clear_abnormal_quick(self, station: str):
        self.clear_abnormal_station_var.set(station)
        self._send_clear_abnormal(station)

    def _send_clear_abnormal(self, station: str):
        if not self._require_connection():
            return

        def do():
            resp = self.simulator.notify_clear_station_abnormal(station)
            self.root.after(0, lambda: self._log_response(f"解除工作站异常状态(2003) - 工作站{station}", resp))
            self._add_history_record({
                "type": "query",
                "timestamp": int(time.time() * 1000),
                "task_id": "",
                "summary": f"解除异常状态 - 工作站{station}",
                "data": resp,
            })

        self._run_in_thread(do)
        self._log(f"已发送解除工作站异常状态通知: 工作站{station}")

    # ────────────── Putaway Actions ──────────────

    def _refresh_location_combo(self):
        station = self.put_station.get()
        locations = [f"{station}{layer}{pos}" for layer in range(1, 5) for pos in range(1, 5)]
        self.put_loc_combo['values'] = locations
        if locations:
            self.put_loc_combo.set(locations[0])

    def _put_fill_all(self):
        items = self.put_tree.get_children()
        if items and not messagebox.askyesno("确认", "将覆盖已有库位数据，继续？"):
            return

        station = self.put_station.get()
        sku = self.put_sku.get().strip()
        qty = self.put_qty.get()
        if not sku:
            messagebox.showwarning("提示", "请输入SKU")
            return

        self.put_tree.delete(*items)
        for layer in range(1, 5):
            for pos in range(1, 5):
                loc = f"{station}{layer}{pos}"
                skus = [sku] * qty
                self.put_tree.insert('', tk.END, values=(loc, ",".join(skus), qty))

        self._log(f"已填满 {station} 全部16个库位: SKU={sku}, 每格{qty}件")

    def _put_generate_random(self):
        items = self.put_tree.get_children()
        if items and not messagebox.askyesno("确认", "随机生成会覆盖已有库位数据，继续？"):
            return

        station = self.put_station.get()
        selected_locations = []
        for layer in range(1, 5):
            positions = list(range(1, 5))
            random.shuffle(positions)
            for pos in positions[:2]:
                selected_locations.append(f"{station}{layer}{pos}")

        self.put_tree.delete(*items)
        target_total = random.randint(18, 22)
        slot_counts = self._random_putaway_slot_counts(
            slot_count=len(selected_locations),
            target_total=target_total,
        )
        sku_types = [f"SKU{index}" for index in range(1, random.randint(4, 5) + 1)]

        for loc, slot_qty in zip(selected_locations, slot_counts):
            sku = random.choice(sku_types)
            skus = [sku] * slot_qty
            self.put_tree.insert('', tk.END, values=(loc, ",".join(skus), slot_qty))

        total_count = sum(
            int(self.put_tree.item(item, "values")[2])
            for item in self.put_tree.get_children()
        )
        self._log(
            f"已随机生成放货任务: 工作站={station}, "
            f"库位数={len(selected_locations)}, 货物数={total_count}，"
            f"SKU种类={len(sku_types)}，每层2个库位有货，每个库位内 SKU 均相同"
        )

    def _random_putaway_slot_counts(self, slot_count: int, target_total: int) -> list[int]:
        counts = [1] * slot_count
        remaining = target_total - slot_count

        while remaining > 0:
            available_indexes = [
                index
                for index, count in enumerate(counts)
                if count < 4
            ]
            if not available_indexes:
                break

            index = random.choice(available_indexes)
            add_count = random.randint(1, min(4 - counts[index], remaining))
            counts[index] += add_count
            remaining -= add_count

        random.shuffle(counts)
        return counts

    def _put_fill_layer(self):
        station = self.put_station.get()
        layer = self.put_layer.get()
        sku = self.put_sku.get().strip()
        qty = self.put_qty.get()
        if not sku:
            messagebox.showwarning("提示", "请输入SKU")
            return

        for pos in range(1, 5):
            loc = f"{station}{layer}{pos}"
            skus = [sku] * qty
            self._put_tree_upsert(loc, skus)

        self._log(f"已填满 {station}{layer}层 4个库位: SKU={sku}, 每格{qty}件")

    def _put_add_manual(self):
        loc = self.put_loc.get().strip()
        sku_str = self.put_loc_sku.get().strip()
        qty = self.put_loc_qty.get()
        if not loc or not sku_str:
            messagebox.showwarning("提示", "请输入库位和SKU")
            return
        base_skus = [s.strip() for s in sku_str.split(",") if s.strip()]
        skus = base_skus * qty
        self._put_tree_upsert(loc, skus)
        self._log(f"添加库位 {loc}: {len(skus)}件 {skus}")

    def _put_tree_upsert(self, location: str, skus: list[str]):
        for item in self.put_tree.get_children():
            vals = self.put_tree.item(item, 'values')
            if vals[0] == location:
                self.put_tree.item(item, values=(location, ",".join(skus), len(skus)))
                return
        self.put_tree.insert('', tk.END, values=(location, ",".join(skus), len(skus)))

    def _put_del_selected(self):
        for item in self.put_tree.selection():
            self.put_tree.delete(item)

    def _put_clear(self):
        self.put_tree.delete(*self.put_tree.get_children())

    def _put_send(self):
        if not self._require_connection():
            return
        items = self.put_tree.get_children()
        if not items:
            messagebox.showwarning("提示", "请先添加库位货物")
            return

        put_goods = []
        for item in items:
            loc, sku_str, count = self.put_tree.item(item, 'values')
            skus = [s.strip() for s in sku_str.split(",") if s.strip()]
            put_goods.append({
                "storage_location": loc,
                "abr_count": int(count),
                "good_sku": skus,
            })

        task_data = {
            "task_id": self.put_tid.get().strip(),
            "task_types": "putaway",
            "timestamp": str(int(time.time() * 1000)),
            "station_id": self.put_station.get(),
            "put_goods": put_goods,
        }

        self._last_put_task = task_data

        total_goods = sum(g["abr_count"] for g in put_goods)
        self._add_history_record({
            "type": "putaway",
            "timestamp": int(time.time() * 1000),
            "task_id": task_data.get("task_id", ""),
            "summary": f"{len(put_goods)}个库位, {total_goods}件货物, 工作站={task_data.get('station_id', '')}",
            "data": copy.deepcopy(task_data),
        })

        def do():
            resp = self.simulator.dispatch_outbound_task(task_data)
            self.root.after(0, lambda: self._log_response("放货任务下发响应", resp))

        self._run_in_thread(do)
        self._log(f"已发送放货任务: {len(put_goods)}个库位")

    def _put_repeat_last(self):
        if not self._require_connection():
            return
        if not self._last_put_task:
            messagebox.showwarning("提示", "没有上次放货任务记录")
            return

        task_data = copy.deepcopy(self._last_put_task)
        task_data["task_id"] = f"PUT_{int(time.time())}"
        task_data["timestamp"] = str(int(time.time() * 1000))

        def do():
            resp = self.simulator.dispatch_outbound_task(task_data)
            self.root.after(0, lambda: self._log_response("重复放货任务响应", resp))

        self._run_in_thread(do)
        self._log(f"重复上次放货任务: {len(task_data['put_goods'])}个库位")

    # ────────────── Outbound Actions ──────────────

    def _out_add_one(self):
        pid = self.out_pkg_id.get().strip()
        if not pid:
            messagebox.showwarning("提示", "请输入包裹ID")
            return
        self._out_add_package(pid)
        self.out_pkg_id.set("")

    def _out_add_batch(self):
        n = self.out_batch_n.get()
        base_id = f"PKG_{int(time.time())}"
        for i in range(n):
            self._out_add_package(f"{base_id}_{i + 1}")
        self._log(f"批量添加 {n} 个包裹")

    def _out_add_package(self, pid: str):
        goods_str = self.out_goods_default.get().strip()
        goods = [s.strip() for s in goods_str.split(",") if s.strip()]
        self.out_tree.insert('', tk.END, values=(
            pid,
            self.out_box.get(),
            self.out_face.get(),
            self.out_logi.get(),
            self.out_manual.get(),
            self.out_pline.get(),
            ",".join(goods),
        ))

    def _out_del_selected(self):
        for item in self.out_tree.selection():
            self.out_tree.delete(item)

    def _out_clear(self):
        self.out_tree.delete(*self.out_tree.get_children())

    def _out_send(self):
        if not self._require_connection():
            return
        items = self.out_tree.get_children()
        if not items:
            messagebox.showwarning("提示", "请先添加包裹")
            return

        packages = []
        for item in items:
            vals = self.out_tree.item(item, 'values')
            goods = [s.strip() for s in vals[6].split(",") if s.strip()]
            packages.append({
                "package_id": vals[0],
                "box_type": vals[1],
                "face_sheet": vals[2],
                "logistics": vals[3],
                "manual_process_type": vals[4],
                "packaging_line": vals[5],
                "count": len(goods),
                "goods": goods,
            })

        task_data = {
            "task_id": self.out_tid.get().strip(),
            "task_types": "outbound",
            "timestamp": str(int(time.time() * 1000)),
            "package_count": len(packages),
            "packages": packages,
        }

        self._last_out_task = task_data

        total_goods = sum(p["count"] for p in packages)
        self._add_history_record({
            "type": "outbound",
            "timestamp": int(time.time() * 1000),
            "task_id": task_data.get("task_id", ""),
            "summary": f"{len(packages)}个包裹, {total_goods}件货物",
            "data": copy.deepcopy(task_data),
        })

        def do():
            resp = self.simulator.dispatch_outbound_task(task_data)
            self.root.after(0, lambda: self._log_response("出库任务下发响应", resp))

        self._run_in_thread(do)
        self._log(f"已发送出库任务: {len(packages)}个包裹")

    def _out_repeat_last(self):
        if not self._require_connection():
            return
        if not self._last_out_task:
            messagebox.showwarning("提示", "没有上次出库任务记录")
            return

        task_data = copy.deepcopy(self._last_out_task)
        task_data["task_id"] = f"OUT_{int(time.time())}"
        task_data["timestamp"] = str(int(time.time() * 1000))

        def do():
            resp = self.simulator.dispatch_outbound_task(task_data)
            self.root.after(0, lambda: self._log_response("重复出库任务响应", resp))

        self._run_in_thread(do)
        self._log(f"重复上次出库任务: {len(task_data['packages'])}个包裹")

    def _out_generate_station_a(self):
        self._out_generate_from_storage_filtered(station_filter="A")

    def _out_generate_all_stations(self):
        self._out_generate_from_storage_filtered(station_filter=None)

    def _out_generate_from_storage_filtered(self, station_filter: str | None):
        if not self._require_connection():
            return

        if self.out_tree.get_children():
            label = "工作站A" if station_filter else "全站"
            if not messagebox.askyesno("确认", f"随机生成({label})会覆盖当前出库包裹列表，继续？"):
                return

        def do():
            storage_resp = self.simulator.query_outbound_storage()
            if storage_resp.get("ret_code", 0) != 0:
                err_msg = storage_resp.get("err_msg", "查询库位信息失败")
                self.root.after(0, lambda err_msg=err_msg: messagebox.showerror("生成失败", err_msg))
                return

            try:
                container = storage_resp.get("container", [])
                if station_filter:
                    container = [
                        item for item in container
                        if (item.get("storage_bin") or item.get("storage_location") or item.get("location_code", "")).startswith(station_filter)
                    ]
                packages = self._build_full_drain_packages(container)
                task_data = {
                    "task_id": f"OUT_{int(time.time())}",
                    "task_types": "outbound",
                    "timestamp": str(int(time.time() * 1000)),
                    "package_count": len(packages),
                    "packages": packages,
                }
                saved_path = self._save_generated_outbound_case(container, task_data)
            except Exception as exc:
                self.root.after(0, lambda exc=exc: messagebox.showerror("生成失败", str(exc)))
                return

            self.root.after(
                0,
                lambda: self._apply_generated_outbound_task(task_data, saved_path),
            )

        self._run_in_thread(do)

    def _build_full_drain_packages(self, container: list[dict]) -> list[dict]:
        storage_snapshot = self._normalize_container_goods(container)
        goods_pool = [
            sku
            for slot in storage_snapshot
            for sku in slot["goods"]
        ]
        if not goods_pool:
            raise ValueError("当前库位没有货物，无法生成出库任务")

        random.shuffle(goods_pool)
        packages: list[dict] = []
        package_index = 1
        total = len(goods_pool)

        if total == 1:
            packages.append(self._build_generated_package(package_index, [goods_pool.pop()]))
            random.shuffle(packages)
            self._assert_generated_packages_match_inventory(packages, storage_snapshot)
            return packages

        if total == 2:
            packages.append(self._build_generated_package(package_index, [goods_pool.pop(), goods_pool.pop()]))
            random.shuffle(packages)
            self._assert_generated_packages_match_inventory(packages, storage_snapshot)
            return packages

        multi_size = random.randint(2, min(4, total - 1))
        multi_goods = [goods_pool.pop() for _ in range(multi_size)]
        packages.append(self._build_generated_package(package_index, multi_goods))
        package_index += 1

        if goods_pool:
            single_goods = [goods_pool.pop()]
            packages.append(self._build_generated_package(package_index, single_goods))
            package_index += 1

        while goods_pool:
            remaining = len(goods_pool)
            if remaining >= 2 and random.random() < 0.35:
                size = random.randint(2, min(4, remaining))
            else:
                size = 1

            pkg_goods = [goods_pool.pop() for _ in range(size)]
            packages.append(self._build_generated_package(package_index, pkg_goods))
            package_index += 1

        random.shuffle(packages)
        self._assert_generated_packages_match_inventory(packages, storage_snapshot)
        return packages

    def _normalize_container_goods(self, container: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for item in container:
            location = item.get("storage_bin") or item.get("storage_location") or item.get("location_code")
            if not location:
                continue

            raw_goods = item.get("goods", [])
            if isinstance(raw_goods, str):
                goods = [sku.strip() for sku in raw_goods.split(",") if sku.strip()]
            elif isinstance(raw_goods, list):
                goods = [str(sku).strip() for sku in raw_goods if str(sku).strip()]
            else:
                goods = []

            qty = int(item.get("qty", len(goods)) or 0)
            if goods and qty != len(goods):
                qty = len(goods)

            normalized.append({
                "storage_bin": location,
                "qty": qty,
                "goods": goods,
            })
        return normalized

    def _build_generated_package(self, package_index: int, goods: list[str]) -> dict:
        count = len(goods)
        packaging_line = "MP1" if count > 1 else random.choice(("HS1", "HS2"))
        package_id = f"PKG_AUTO_{int(time.time())}_{package_index:03d}"
        return {
            "package_id": package_id,
            "box_type": random.choice(BOX_TYPE_OPTIONS),
            "face_sheet": f"FS_AUTO_{package_index:03d}",
            "logistics": random.choice(LOGISTICS_OPTIONS),
            "manual_process_type": "N",
            "packaging_line": packaging_line,
            "count": count,
            "goods": list(goods),
        }

    def _assert_generated_packages_match_inventory(
        self,
        packages: list[dict],
        storage_snapshot: list[dict],
    ) -> None:
        inventory_counter = Counter(
            sku
            for slot in storage_snapshot
            for sku in slot["goods"]
        )
        package_counter = Counter(
            sku
            for package in packages
            for sku in package["goods"]
        )
        overused = {
            sku: {
                "inventory": inventory_counter.get(sku, 0),
                "planned": planned_count,
            }
            for sku, planned_count in package_counter.items()
            if planned_count > inventory_counter.get(sku, 0)
        }
        if overused:
            raise ValueError(f"随机包裹生成数量超过当前库存: {overused}")

        total_planned = sum(len(package["goods"]) for package in packages)
        if total_planned >= 3:
            if not any(len(package["goods"]) == 1 for package in packages):
                raise ValueError("随机包裹生成失败：没有单盒包裹")
            if not any(len(package["goods"]) > 1 for package in packages):
                raise ValueError("随机包裹生成失败：没有多盒包裹")

        for package in packages:
            if len(package["goods"]) > 1 and package["packaging_line"] != "MP1":
                raise ValueError(f"多盒包裹必须走 MP1: {package['package_id']}")
            if len(package["goods"]) == 1 and package["packaging_line"] not in ("HS1", "HS2"):
                raise ValueError(f"单盒包裹必须走 HS1/HS2: {package['package_id']}")
            if package["count"] != len(package["goods"]):
                raise ValueError(f"包裹 count 与 goods 数量不一致: {package['package_id']}")

    def _save_generated_outbound_case(self, container: list[dict], task_data: dict) -> Path:
        storage_snapshot = self._normalize_container_goods(container)
        record = {
            "created_at": int(time.time() * 1000),
            "storage": storage_snapshot,
            "storage_summary": {
                "slot_count": len(storage_snapshot),
                "non_empty_slot_count": sum(1 for slot in storage_snapshot if slot["goods"]),
                "total_goods": sum(len(slot["goods"]) for slot in storage_snapshot),
                "sku_counts": dict(Counter(
                    sku
                    for slot in storage_snapshot
                    for sku in slot["goods"]
                )),
            },
            "outbound_task": task_data,
        }

        if GENERATED_OUTBOUND_FILE.exists():
            with GENERATED_OUTBOUND_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, list):
                data = [data]
        else:
            data = []

        data.append(record)
        with GENERATED_OUTBOUND_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        return GENERATED_OUTBOUND_FILE

    def _apply_generated_outbound_task(self, task_data: dict, saved_path: Path) -> None:
        self.out_tree.delete(*self.out_tree.get_children())
        self.out_tid.set(task_data["task_id"])

        for package in task_data["packages"]:
            self.out_tree.insert('', tk.END, values=(
                package["package_id"],
                package["box_type"],
                package["face_sheet"],
                package["logistics"],
                package["manual_process_type"],
                package["packaging_line"],
                ",".join(package["goods"]),
            ))

        self._last_out_task = copy.deepcopy(task_data)
        size_counts = Counter(len(package["goods"]) for package in task_data["packages"])
        self._log(
            f"已根据当前库位随机生成 {len(task_data['packages'])} 个包裹，"
            f"货物数={sum(package['count'] for package in task_data['packages'])}，"
            f"单盒={size_counts.get(1, 0)}，多盒={sum(count for size, count in size_counts.items() if size > 1)}，"
            f"已保存: {saved_path}"
        )

    # ────────────── History Tab ──────────────

    def _build_history_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="  历史记录  ")

        filter_row = ttk.Frame(tab)
        filter_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(filter_row, text="筛选:").pack(side=tk.LEFT, padx=(0, 4))
        self.history_filter = tk.StringVar(value="全部")
        filter_combo = ttk.Combobox(
            filter_row, textvariable=self.history_filter,
            values=["全部", "放货任务", "出库任务", "状态查询"],
            width=10, state="readonly",
        )
        filter_combo.pack(side=tk.LEFT, padx=(0, 8))
        filter_combo.bind("<<ComboboxSelected>>", lambda _: self._refresh_history_tree())

        ttk.Button(filter_row, text="刷新", command=self._load_and_refresh_history, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(filter_row, text="清空历史", command=self._history_clear).pack(side=tk.RIGHT, padx=4)

        self.history_count_var = tk.StringVar(value="共 0 条记录")
        ttk.Label(filter_row, textvariable=self.history_count_var).pack(side=tk.RIGHT, padx=8)

        tree_frame = ttk.Frame(tab)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        cols = ("time", "type", "task_id", "summary")
        self.history_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=14)
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("type", text="类型")
        self.history_tree.heading("task_id", text="任务ID")
        self.history_tree.heading("summary", text="摘要")
        self.history_tree.column("time", width=160, anchor=tk.CENTER)
        self.history_tree.column("type", width=80, anchor=tk.CENTER)
        self.history_tree.column("task_id", width=200, anchor=tk.CENTER)
        self.history_tree.column("summary", width=380)
        self.history_tree.bind("<Double-1>", lambda _: self._history_view_detail())

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=sb.set)
        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = ttk.Frame(tab)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="查看详情", command=self._history_view_detail, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="加载到放货任务", command=self._history_load_putaway, width=14).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="加载到出库任务", command=self._history_load_outbound, width=14).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="删除选中", command=self._history_delete_selected, width=10).pack(side=tk.LEFT, padx=4)

    def _load_history(self):
        if SIMULATOR_HISTORY_FILE.exists():
            try:
                with SIMULATOR_HISTORY_FILE.open("r", encoding="utf-8") as f:
                    self._history_data = json.load(f)
                if not isinstance(self._history_data, list):
                    self._history_data = [self._history_data]
            except Exception:
                self._history_data = []
        else:
            self._migrate_from_generated_outbound()
        if hasattr(self, 'history_tree'):
            self._refresh_history_tree()

    def _load_and_refresh_history(self):
        self._load_history()
        self._log("已刷新历史记录")

    def _migrate_from_generated_outbound(self):
        if not GENERATED_OUTBOUND_FILE.exists():
            self._history_data = []
            return
        try:
            with GENERATED_OUTBOUND_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = [data]
            for record in data:
                task = record.get("outbound_task", {})
                summary_info = record.get("storage_summary", {})
                summary = (
                    f"{task.get('package_count', 0)}个包裹, "
                    f"{summary_info.get('total_goods', 0)}件货物"
                )
                self._history_data.append({
                    "type": "outbound",
                    "timestamp": record.get("created_at", 0),
                    "task_id": task.get("task_id", ""),
                    "summary": summary,
                    "data": copy.deepcopy(task),
                    "storage_snapshot": {
                        "storage": record.get("storage", []),
                        "storage_summary": summary_info,
                    },
                })
            self._save_history_to_file()
            self._log(f"已从 {GENERATED_OUTBOUND_FILE.name} 迁移 {len(data)} 条出库历史记录")
        except Exception as e:
            self._log(f"迁移历史记录失败: {e}")
            self._history_data = []

    def _save_history_to_file(self):
        try:
            with SIMULATOR_HISTORY_FILE.open("w", encoding="utf-8") as f:
                json.dump(self._history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(f"保存历史记录失败: {e}")

    def _add_history_record(self, record: dict):
        self._history_data.append(record)
        self._save_history_to_file()
        self.root.after(0, self._refresh_history_tree)

    def _refresh_history_tree(self):
        if not hasattr(self, 'history_tree'):
            return
        self.history_tree.delete(*self.history_tree.get_children())
        filter_map = {
            "全部": None,
            "放货任务": "putaway",
            "出库任务": "outbound",
            "状态查询": "query",
        }
        selected_type = filter_map.get(self.history_filter.get())
        for i, record in enumerate(self._history_data):
            rec_type = record.get("type", "")
            if selected_type and rec_type != selected_type:
                continue
            ts = record.get("timestamp", 0)
            if ts:
                try:
                    time_str = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    time_str = str(ts)
            else:
                time_str = "-"
            type_display = {"putaway": "放货", "outbound": "出库", "query": "查询"}.get(rec_type, rec_type)
            self.history_tree.insert('', tk.END, iid=str(i), values=(
                time_str,
                type_display,
                record.get("task_id", ""),
                record.get("summary", ""),
            ))
        count = len(self.history_tree.get_children())
        self.history_count_var.set(f"共 {count} 条记录")

    def _get_selected_history_index(self) -> int | None:
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一条历史记录")
            return None
        return int(selection[0])

    def _history_view_detail(self):
        idx = self._get_selected_history_index()
        if idx is None:
            return
        if idx >= len(self._history_data):
            return
        record = self._history_data[idx]
        detail = {
            "type": record.get("type", ""),
            "timestamp": record.get("timestamp", 0),
            "task_id": record.get("task_id", ""),
            "summary": record.get("summary", ""),
        }
        if record.get("storage_snapshot"):
            detail["storage_snapshot"] = record["storage_snapshot"]
        if record.get("data"):
            detail["data"] = record["data"]
        type_label = {"putaway": "放货任务", "outbound": "出库任务", "query": "状态查询"}.get(detail["type"], detail["type"])
        self._log_response(f"历史记录详情 [{type_label}] {detail.get('task_id', '')}", detail)

    def _history_load_putaway(self):
        idx = self._get_selected_history_index()
        if idx is None:
            return
        if idx >= len(self._history_data):
            return
        record = self._history_data[idx]
        if record.get("type") != "putaway":
            messagebox.showwarning("提示", "请选择一条放货任务记录")
            return
        task_data = record.get("data", {})
        put_goods = task_data.get("put_goods", [])
        if not put_goods:
            messagebox.showwarning("提示", "该记录没有放货数据")
            return
        self.put_tree.delete(*self.put_tree.get_children())
        for good in put_goods:
            loc = good.get("storage_location", "")
            skus = good.get("good_sku", [])
            count = good.get("abr_count", 0)
            self.put_tree.insert('', tk.END, values=(loc, ",".join(skus), count))
        self.put_tid.set(task_data.get("task_id", f"PUT_{int(time.time())}"))
        self.put_station.set(task_data.get("station_id", "A"))
        self._last_put_task = copy.deepcopy(task_data)
        self.notebook.select(1)
        self._log(f"已加载历史放货任务: {task_data.get('task_id', '')}")

    def _history_load_outbound(self):
        idx = self._get_selected_history_index()
        if idx is None:
            return
        if idx >= len(self._history_data):
            return
        record = self._history_data[idx]
        if record.get("type") != "outbound":
            messagebox.showwarning("提示", "请选择一条出库任务记录")
            return
        task_data = record.get("data", {})
        packages = task_data.get("packages", [])
        if not packages:
            messagebox.showwarning("提示", "该记录没有出库数据")
            return
        self.out_tree.delete(*self.out_tree.get_children())
        for package in packages:
            self.out_tree.insert('', tk.END, values=(
                package.get("package_id", ""),
                package.get("box_type", ""),
                package.get("face_sheet", ""),
                package.get("logistics", ""),
                package.get("manual_process_type", ""),
                package.get("packaging_line", ""),
                ",".join(package.get("goods", [])),
            ))
        self.out_tid.set(task_data.get("task_id", f"OUT_{int(time.time())}"))
        self._last_out_task = copy.deepcopy(task_data)
        self.notebook.select(2)
        self._log(f"已加载历史出库任务: {task_data.get('task_id', '')}")

    def _history_delete_selected(self):
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的记录")
            return
        indices = sorted([int(s) for s in selection], reverse=True)
        for idx in indices:
            if 0 <= idx < len(self._history_data):
                del self._history_data[idx]
        self._save_history_to_file()
        self._refresh_history_tree()
        self._log(f"已删除 {len(indices)} 条历史记录")

    def _history_clear(self):
        if not self._history_data:
            return
        if not messagebox.askyesno("确认", "确定要清空所有历史记录吗？此操作不可恢复。"):
            return
        self._history_data = []
        self._save_history_to_file()
        self._refresh_history_tree()
        self._log("已清空所有历史记录")

    # ────────────── Close ──────────────

    def _on_close(self):
        if self.simulator:
            try:
                self.simulator.close()
            except Exception:
                pass
        self.root.destroy()


if __name__ == '__main__':
    app = SimulatorApp()
    app.run()
