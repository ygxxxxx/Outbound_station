import tkinter as tk
from tkinter import ttk, messagebox
from src.communication.rcs_sever_protocol import decode, encode
from src.utils.logger import logger

import socket
import time
import random
import threading
import copy

logger = logger.bind(tag='rcs_client_simulator')


# ── Constants ───────────────────────────────────────────────────────

STATION_IDS = ("A", "B", "C")
LOGISTICS_OPTIONS = ("shunfeng", "yunda", "zhongtong", "yuantong", "jd", "ems")
MANUAL_PROCESS_OPTIONS = ("N", "G", "S")
PACKAGING_LINE_OPTIONS = ("HS1", "HS2", "MP1", "MA1", "MO1")
BOX_TYPE_OPTIONS = ("DW01-A", "DW01-B", "DW02-A", "DW02-B")


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

        self.root = tk.Tk()
        self.root.title("RCS 客户端模拟器")
        self.root.geometry("1060x800")
        self.root.minsize(860, 640)

        self._build_connection_panel()
        self._build_notebook()
        self._build_response_panel()
        self._build_status_bar()

        self._set_connected(False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self):
        self.root.mainloop()

    # ────────────── Connection Panel ──────────────

    def _build_connection_panel(self):
        frame = ttk.LabelFrame(self.root, text="连接设置", padding=8)
        frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(frame, text="主机:").pack(side=tk.LEFT, padx=(0, 4))
        self.host_var = tk.StringVar(value="127.0.0.1")
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

        ttk.Label(qf, text="指定层:").grid(row=0, column=5, padx=4)
        self.put_layer = tk.IntVar(value=1)
        ttk.Spinbox(qf, from_=1, to=4, textvariable=self.put_layer, width=4).grid(row=0, column=6, padx=4)

        ttk.Button(qf, text="填满指定层(4格)", command=self._put_fill_layer).grid(row=0, column=7, padx=8)

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
        self.put_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=5)
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
        self.out_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=5)
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
        ttk.Button(btn_row, text="下发出库任务", command=self._out_send).pack(side=tk.RIGHT, padx=4)

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

        self.resp_text = tk.Text(text_frame, height=10, wrap=tk.WORD, state=tk.DISABLED,
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

        self._run_in_thread(do)

    def _do_query(self, label: str, query_fn):
        resp = query_fn()
        self.root.after(0, lambda: self._log_response(label, resp))

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
