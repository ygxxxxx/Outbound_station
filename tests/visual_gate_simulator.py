import socket
import struct
import json
import threading
import time
import tkinter as tk
from tkinter import ttk

SYNC_BYTE = 0xAC
PROTO_VERSION = 1
HEADER_SIZE = 10
MSG_TYPE_OUTBOUND_REQ = 1000
MSG_TYPE_OUTBOUND_RES = 11000
HEADER_FORMAT = '!BBHHI'


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None, data
    sync, version, seq, msg_type, data_len = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if sync != SYNC_BYTE:
        return None, data[1:]
    total_len = HEADER_SIZE + data_len
    if len(data) < total_len:
        return None, data
    body_bytes = data[HEADER_SIZE:total_len]
    remain = data[total_len:]
    if data_len > 0:
        try:
            body = json.loads(body_bytes.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, remain
    else:
        body = {}
    return {'seq': seq, 'msg_type': msg_type, 'body': body}, remain


def build_response(seq: int, msg_type: int, body: dict) -> bytes:
    json_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')
    header = struct.pack(HEADER_FORMAT, SYNC_BYTE, PROTO_VERSION, seq, msg_type, len(json_bytes))
    return header + json_bytes


MANUAL_PROCESS_MAP = {"N": "None", "G": "Gift", "S": "Soft"}
PACKAGING_LINE_MAP = {
    "HS1": "High-speed line 1", "HS2": "High-speed line 2",
    "MP1": "Multi-pack line", "MA1": "Manual assembly line",
    "MO1": "Merged order cache line",
}


class VisionGateSimulator:

    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 23320
        self.server_sock = None
        self.client_conn = None
        self.client_addr = None
        self.running = False
        self.connected = False
        self.stop_event = threading.Event()
        self.auto_respond = True
        self.respond_delay = 0.0
        self.respond_error = False
        self.lock = threading.Lock()
        self.request_count = 0

    def start_server(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.settimeout(1.0)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(5)
        self.running = True
        self.stop_event.clear()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop_server(self):
        self.stop_event.set()
        self.running = False
        self.connected = False
        if self.client_conn:
            try:
                self.client_conn.close()
            except OSError:
                pass
            self.client_conn = None
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
            self.server_sock = None

    def _accept_loop(self):
        while not self.stop_event.is_set():
            try:
                conn, addr = self.server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self.client_conn:
                try:
                    self.client_conn.close()
                except OSError:
                    pass
            self.client_conn = conn
            self.client_addr = addr
            self.client_conn.settimeout(1.0)
            self.connected = True
            self._notify_connected(addr)
            self._recv_loop(conn)

    def _recv_loop(self, conn):
        buffer = b''
        while not self.stop_event.is_set():
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buffer += data
            while True:
                result, buffer = parse_packet(buffer)
                if result is None:
                    break
                self._on_request(result, conn)
        self.connected = False
        self._notify_disconnected()

    def _on_request(self, result: dict, conn: socket.socket):
        seq = result['seq']
        msg_type = result['msg_type']
        body = result['body']

        if msg_type != MSG_TYPE_OUTBOUND_REQ:
            resp = build_response(seq, MSG_TYPE_OUTBOUND_RES, {
                "ret_code": -1,
                "create_time": int(time.time() * 1000),
                "err_msg": f"Unknown msg_type: {msg_type}",
            })
            conn.sendall(resp)
            return

        self.request_count += 1
        self._notify_request(seq, body)

        if self.auto_respond:
            def delayed_respond():
                if self.respond_delay > 0:
                    time.sleep(self.respond_delay)
                if self.stop_event.is_set():
                    return
                if self.respond_error:
                    resp_body = {
                        "ret_code": -1,
                        "create_time": int(time.time() * 1000),
                        "err_msg": "Simulated error",
                    }
                else:
                    resp_body = {
                        "ret_code": 0,
                        "create_time": int(time.time() * 1000),
                    }
                resp = build_response(seq, MSG_TYPE_OUTBOUND_RES, resp_body)
                try:
                    conn.sendall(resp)
                except OSError:
                    pass
                self._notify_response(seq, resp_body)
            threading.Thread(target=delayed_respond, daemon=True).start()

    def send_manual_response(self, seq: int, ret_code: int, err_msg: str):
        if not self.client_conn or not self.connected:
            return
        resp_body = {
            "ret_code": ret_code,
            "create_time": int(time.time() * 1000),
        }
        if err_msg:
            resp_body["err_msg"] = err_msg
        resp = build_response(seq, MSG_TYPE_OUTBOUND_RES, resp_body)
        try:
            self.client_conn.sendall(resp)
        except OSError:
            pass
        self._notify_response(seq, resp_body)

    _on_connected = None
    _on_disconnected = None
    _on_request_received = None
    _on_response_sent = None

    def _notify_connected(self, addr):
        if self._on_connected:
            self._on_connected(addr)

    def _notify_disconnected(self):
        if self._on_disconnected:
            self._on_disconnected()

    def _notify_request(self, seq, body):
        if self._on_request_received:
            self._on_request_received(seq, body)

    def _notify_response(self, seq, body):
        if self._on_response_sent:
            self._on_response_sent(seq, body)


class SimulatorApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("视觉门模拟器")
        self.root.geometry("1100x750")
        self.root.resizable(True, True)

        self.sim = VisionGateSimulator()
        self.sim._on_connected = self._ui_on_connected
        self.sim._on_disconnected = self._ui_on_disconnected
        self.sim._on_request_received = self._ui_on_request
        self.sim._on_response_sent = self._ui_on_response
        self.last_request_seq = None
        self.last_request_body = None

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=5)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Port:").pack(side=tk.LEFT, padx=(0, 4))
        self.port_var = tk.StringVar(value="23320")
        port_combo = ttk.Combobox(top, textvariable=self.port_var, width=8, state="readonly",
                                  values=["23320", "23321"])
        port_combo.pack(side=tk.LEFT, padx=(0, 12))

        self.start_btn = ttk.Button(top, text="Start", command=self._toggle_server)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(top, textvariable=self.status_var, foreground="red", font=("", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Auto Respond", variable=self.auto_var,
                        command=self._update_sim_config).pack(side=tk.LEFT, padx=(0, 8))

        self.error_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Respond Error", variable=self.error_var,
                        command=self._update_sim_config).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(top, text="Delay(s):").pack(side=tk.LEFT, padx=(0, 4))
        self.delay_var = tk.StringVar(value="0")
        delay_entry = ttk.Entry(top, textvariable=self.delay_var, width=5)
        delay_entry.pack(side=tk.LEFT, padx=(0, 4))
        delay_entry.bind("<KeyRelease>", lambda e: self._update_sim_config())

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.manual_btn = ttk.Button(top, text="Manual Send Success", command=self._manual_send_success,
                                     state=tk.DISABLED)
        self.manual_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.manual_err_btn = ttk.Button(top, text="Manual Send Error", command=self._manual_send_error,
                                         state=tk.DISABLED)
        self.manual_err_btn.pack(side=tk.LEFT)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        goods_frame = ttk.Frame(notebook)
        notebook.add(goods_frame, text="  Goods List  ")
        self._build_goods_table(goods_frame)

        log_frame = ttk.Frame(notebook)
        notebook.add(log_frame, text="  Request Log  ")
        self._build_log_panel(log_frame)

    def _build_goods_table(self, parent):
        columns = ("seq", "package_id", "good_sku", "box_type", "face_sheet",
                    "logistics", "manual_process_type", "packaging_line")
        headers = ("#", "Package ID", "SKU", "Box Type", "Face Sheet",
                   "Logistics", "Manual Process", "Packaging Line")

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        x_scroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        self.goods_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set,
            height=20,
        )
        y_scroll.config(command=self.goods_tree.yview)
        x_scroll.config(command=self.goods_tree.xview)

        for col, header in zip(columns, headers):
            self.goods_tree.heading(col, text=header)
            w = 120 if col not in ("seq",) else 40
            self.goods_tree.column(col, width=w, minwidth=40)

        self.goods_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        info_frame = ttk.Frame(parent)
        info_frame.pack(fill=tk.X, pady=(4, 0))
        self.goods_info_var = tk.StringVar(value="Waiting for data...")
        ttk.Label(info_frame, textvariable=self.goods_info_var, font=("", 9)).pack(side=tk.LEFT)

        btn_frame = ttk.Frame(info_frame)
        btn_frame.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Clear", command=self._clear_goods_table).pack(side=tk.RIGHT)

    def _build_log_panel(self, parent):
        self.log_text = tk.Text(parent, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED)
        log_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_config("req", foreground="#0066CC")
        self.log_text.tag_config("res_ok", foreground="#009900")
        self.log_text.tag_config("res_err", foreground="#CC0000")
        self.log_text.tag_config("info", foreground="#666666")

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(btn_frame, text="Clear Log", command=self._clear_log).pack(side=tk.RIGHT)

    def _toggle_server(self):
        if self.sim.running:
            self.sim.stop_server()
            self.start_btn.config(text="Start")
            self.status_var.set("Stopped")
            self.status_label.config(foreground="red")
            self.manual_btn.config(state=tk.DISABLED)
            self.manual_err_btn.config(state=tk.DISABLED)
        else:
            self.sim.port = int(self.port_var.get())
            self._update_sim_config()
            try:
                self.sim.start_server()
                self.start_btn.config(text="Stop")
                self.status_var.set(f"Listening on :{self.sim.port}")
                self.status_label.config(foreground="#CC8800")
            except OSError as e:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, f"[ERROR] Failed to start: {e}\n", "res_err")
                self.log_text.config(state=tk.DISABLED)

    def _update_sim_config(self, *_):
        self.sim.auto_respond = self.auto_var.get()
        self.sim.respond_error = self.error_var.get()
        try:
            self.sim.respond_delay = float(self.delay_var.get())
        except ValueError:
            self.sim.respond_delay = 0.0

        if self.auto_var.get():
            self.manual_btn.config(state=tk.DISABLED)
            self.manual_err_btn.config(state=tk.DISABLED)
        elif self.sim.connected:
            self.manual_btn.config(state=tk.NORMAL)
            self.manual_err_btn.config(state=tk.NORMAL)

    def _manual_send_success(self):
        if self.last_request_seq is not None:
            self.sim.send_manual_response(self.last_request_seq, 0, "")

    def _manual_send_error(self):
        if self.last_request_seq is not None:
            self.sim.send_manual_response(self.last_request_seq, -1, "Manual error from simulator")

    def _ui_on_connected(self, addr):
        self.root.after(0, self._do_connected, addr)

    def _do_connected(self, addr):
        self.status_var.set(f"Connected: {addr[0]}:{addr[1]}")
        self.status_label.config(foreground="green")
        if not self.auto_var.get():
            self.manual_btn.config(state=tk.NORMAL)
            self.manual_err_btn.config(state=tk.NORMAL)
        self._append_log(f"--- Client connected: {addr[0]}:{addr[1]} ---\n", "info")

    def _ui_on_disconnected(self):
        self.root.after(0, self._do_disconnected)

    def _do_disconnected(self):
        if self.sim.running:
            self.status_var.set(f"Listening on :{self.sim.port}")
            self.status_label.config(foreground="#CC8800")
        self.manual_btn.config(state=tk.DISABLED)
        self.manual_err_btn.config(state=tk.DISABLED)
        self._append_log("--- Client disconnected ---\n", "info")

    def _ui_on_request(self, seq, body):
        self.root.after(0, self._do_request, seq, body)

    def _do_request(self, seq, body):
        self.last_request_seq = seq
        self.last_request_body = body

        timestamp = body.get("timestamp", "")
        good_count = body.get("good_count", 0)
        goods = body.get("goods", [])

        self._append_log(
            f"\n[REQ #{self.sim.request_count}] seq={seq}, msg_type=1000, "
            f"timestamp={timestamp}, good_count={good_count}\n", "req"
        )
        for g in goods:
            line = (f"  #{g.get('sequence', '?')} | pkg={g.get('package_id', '')} | "
                    f"sku={g.get('good_sku', '')} | box={g.get('box_type', '')} | "
                    f"face={g.get('face_sheet', '')} | log={g.get('logistics', '')} | "
                    f"manual={g.get('manual_process_type', '')} | "
                    f"line={g.get('packaging_line', '')}\n")
            self._append_log(line, "req")

        for item in goods:
            s = item.get("sequence", "")
            self.goods_tree.insert("", tk.END, values=(
                s,
                item.get("package_id", ""),
                item.get("good_sku", ""),
                item.get("box_type", ""),
                item.get("face_sheet", ""),
                item.get("logistics", ""),
                item.get("manual_process_type", ""),
                item.get("packaging_line", ""),
            ))

        total = len(self.goods_tree.get_children())
        self.goods_info_var.set(
            f"Last request: seq={seq}, good_count={good_count} | Total records in table: {total}"
        )

        self.goods_tree.yview_moveto(1.0)

        if not self.auto_var.get():
            self._append_log(f"  >> Waiting for manual response... (seq={seq})\n", "info")

    def _ui_on_response(self, seq, body):
        self.root.after(0, self._do_response, seq, body)

    def _do_response(self, seq, body):
        ret_code = body.get("ret_code", 0)
        err_msg = body.get("err_msg", "")
        tag = "res_ok" if ret_code == 0 else "res_err"
        self._append_log(
            f"[RES] seq={seq}, ret_code={ret_code}"
            + (f", err_msg={err_msg}" if err_msg else "")
            + f", create_time={body.get('create_time', '')}\n", tag
        )

    def _append_log(self, text, tag=None):
        self.log_text.config(state=tk.NORMAL)
        if tag:
            self.log_text.insert(tk.END, text, tag)
        else:
            self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_goods_table(self):
        for item in self.goods_tree.get_children():
            self.goods_tree.delete(item)
        self.goods_info_var.set("Table cleared. Waiting for data...")

    def on_close(self):
        self.sim.stop_server()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SimulatorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
