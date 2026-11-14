# -*- coding: utf-8 -*-
"""无双IPTV抓源工具 · Windows 单文件绿色版
接线向导 → pktmon 抓包分析 → 原生组播验证 → M3U 生成/目录更新 → 可选 HTTP 转发。
全国 31 省×运营商组播参考库，支持在线更新/离线导入。
作者：锤无双  https://www.bilibili.com/video/BV17SWk6VEPZ/
"""
import copy
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture
import channeldb
import m3u
import naspush
import netutil
import proxy
import refupdate
import verify
import wizard

APP_NAME = '无双IPTV抓源工具'
APP_VER = '2.0.0'
AUTHOR = '锤无双'
AUTHOR_URL = 'https://www.bilibili.com/video/BV17SWk6VEPZ/'
TUTORIAL_URL = 'https://www.bilibili.com/video/BV17SWk6VEPZ/'
QQ_GROUP = '170621740'

# ---- 配色 ----
BG = '#f2f5fa'
CARD = '#ffffff'
ACCENT = '#2563eb'
ACCENT_DARK = '#1d4ed8'
TEXT = '#1f2937'
SUB = '#64748b'
OKC = '#16a34a'
BADC = '#dc2626'
WARNC = '#d97706'
FONT = ('Microsoft YaHei UI', 10)
FONT_B = ('Microsoft YaHei UI', 10, 'bold')
FONT_S = ('Microsoft YaHei UI', 9)
MONO = ('Consolas', 10)


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CFG_PATH = os.path.join(app_dir(), 'WushuangIPTV.json')

DEFAULT_CFG = {
    'wizard': {'mode': 'fresh', 'pc_lan': 'yes', 'pc_wifi': 'yes', 'switch': 'dumb3',
               'stb_lan': 'yes', 'ont_port': 'unknown', 'router_wan': 'ont'},
    'channels': [],
    'out_dir': '', 'out_name': 'iptv.m3u',
    'fmt': 'udp', 'udpxy_host': '', 'udpxy_port': 9999, 'logo_base': '',
    'only_ok': True, 'merge_file': True, 'auto_update': False, 'pair_file': True,
    'proxy_port': 9999, 'keep_pcap': False, 'auto_stop_sec': 90,
    'verify_concurrency': 4, 'verify_timeout': 5,
    'last_province': '', 'last_carrier': '',
    'nas_method': 'smb', 'nas_path': '', 'nas_webdav': '', 'nas_user': '',
    'nas_pass': '', 'nas_auto': False,
}


class EditDialog(tk.Toplevel):
    def __init__(self, master, title, fields, values=None):
        super().__init__(master)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        self.vars = {}
        values = values or {}
        for i, (key, label, default) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky='e', padx=10, pady=5)
            v = tk.StringVar(value=str(values.get(key, default)))
            ttk.Entry(self, textvariable=v, width=36).grid(row=i, column=1, padx=10, pady=5)
        bf = ttk.Frame(self)
        bf.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='确定', style='Accent.TButton', command=self._ok).pack(side='left', padx=6)
        ttk.Button(bf, text='取消', command=self.destroy).pack(side='left', padx=6)
        self.transient(master)
        self.grab_set()
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.wait_window(self)

    def _ok(self):
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.destroy()


class RefDialog(tk.Toplevel):
    """选择省份+运营商载入参考库。"""

    def __init__(self, master, last_prov='', last_carrier=''):
        super().__init__(master)
        self.title('选择地区载入参考库')
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        info = channeldb.db_info()
        ttk.Label(self, text='全国组播参考库', font=('Microsoft YaHei UI', 12, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w', padx=14, pady=(12, 2))
        ttk.Label(self, style='Hint.TLabel',
                  text='数据更新：%s · 来源：%s · %d 省 %d 列表 %d 频道' % (
                      info['updated'], info['origin'], info['provinces'],
                      info['regions'], info['channels'])).grid(
            row=1, column=0, columnspan=2, sticky='w', padx=14)
        ttk.Label(self, text='省份/直辖市：').grid(row=2, column=0, sticky='e', padx=10, pady=8)
        self.prov_cb = ttk.Combobox(self, width=24, state='readonly', values=channeldb.provinces())
        self.prov_cb.grid(row=2, column=1, sticky='w', padx=10, pady=8)
        ttk.Label(self, text='运营商：').grid(row=3, column=0, sticky='e', padx=10, pady=8)
        self.carrier_cb = ttk.Combobox(self, width=24, state='readonly')
        self.carrier_cb.grid(row=3, column=1, sticky='w', padx=10, pady=8)
        self.count_lbl = ttk.Label(self, text='', style='Hint.TLabel')
        self.count_lbl.grid(row=4, column=0, columnspan=2, sticky='w', padx=14)
        bf = ttk.Frame(self)
        bf.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Button(bf, text='载入到频道列表', style='Accent.TButton', command=self._ok).pack(side='left', padx=6)
        ttk.Button(bf, text='取消', command=self.destroy).pack(side='left', padx=6)
        self.prov_cb.bind('<<ComboboxSelected>>', self._prov_sel)
        self.carrier_cb.bind('<<ComboboxSelected>>', lambda e: self._count())
        provs = channeldb.provinces()
        if last_prov in provs:
            self.prov_cb.set(last_prov)
        elif provs:
            self.prov_cb.set(provs[0])
        self._prov_sel()
        if last_carrier:
            for label, carrier, _n in channeldb.carriers(self.prov_cb.get()):
                if carrier == last_carrier:
                    self.carrier_cb.set(label)
                    break
        self.transient(master)
        self.grab_set()
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.wait_window(self)

    def _prov_sel(self, _evt=None):
        prov = self.prov_cb.get()
        cs = channeldb.carriers(prov)
        self.carrier_cb['values'] = ['%s（%d 频道）' % (l, n) for l, c, n in cs]
        self._cs = cs
        if cs:
            self.carrier_cb.current(0)
        self._count()

    def _count(self):
        prov = self.prov_cb.get()
        idx = self.carrier_cb.current()
        if idx >= 0 and idx < len(self._cs):
            _l, carrier, n = self._cs[idx]
            self.count_lbl.config(text='「%s%s」共 %d 个频道，载入后请实测验证可用性。' % (prov, carrier, n))

    def _ok(self):
        idx = self.carrier_cb.current()
        if self.prov_cb.get() and idx >= 0:
            self.result = (self.prov_cb.get(), self._cs[idx][1])
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title('%s v%s' % (APP_NAME, APP_VER))
        root.geometry('1180x820')
        root.minsize(1040, 700)
        root.configure(bg=BG)
        try:
            root.tk.call('tk', 'scaling', 1.25)
        except tk.TclError:
            pass
        self.cfg = self._load_cfg()
        self.channels = self.cfg.get('channels', [])
        self.ifaces = netutil.list_interfaces()
        self.q = queue.Queue()
        self.pktmon = capture.Pktmon(os.path.join(app_dir(), 'cap_temp'))
        self.proxy_srv = None
        self.cap_thread = None
        self.ver_thread = None
        self.upd_thread = None
        self.ver_stop = threading.Event()
        self.upd_stop = threading.Event()
        self.cap_started = None
        self.cap_stopping = False
        self.cap_flows = []
        self.cap_joins = {}
        self.last_save = ''
        self._build_style()
        self._build_banner()
        self._build_menu()
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='both', expand=True, padx=8, pady=(6, 0))
        self._build_wizard()
        self._build_capture()
        self._build_verify()
        self._build_m3u()
        self._build_proxy()
        self._build_help()
        self._build_status()
        self._refresh_iface_widgets()
        self._reload_channel_tree()
        self.root.after(100, self._poll)
        self.root.after(1000, self._tick)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ================= 配置 =================
    def _load_cfg(self):
        cfg = copy.deepcopy(DEFAULT_CFG)
        try:
            with open(CFG_PATH, encoding='utf-8') as f:
                data = json.load(f)
            for k, v in data.items():
                if k in cfg:
                    cfg[k] = v
        except (OSError, ValueError):
            pass
        return cfg

    def _save_cfg(self):
        self.cfg['channels'] = self.channels
        try:
            with open(CFG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=1)
        except OSError as e:
            self._log('配置保存失败: %s' % e)

    # ================= 样式 =================
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use('clam')
        except tk.TclError:
            pass
        st.configure('.', font=FONT, background=BG, foreground=TEXT)
        st.configure('TFrame', background=BG)
        st.configure('TLabel', background=BG, foreground=TEXT)
        st.configure('TLabelframe', background=BG, foreground=ACCENT_DARK,
                     borderwidth=1, relief='solid', bordercolor='#dfe5ee')
        st.configure('TLabelframe.Label', background=BG, foreground=ACCENT_DARK, font=FONT_B)
        st.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(6, 6, 6, 0))
        st.configure('TNotebook.Tab', background='#e6ebf2', foreground=SUB,
                     padding=(18, 8), font=FONT_B, borderwidth=0)
        st.map('TNotebook.Tab', background=[('selected', CARD)],
               foreground=[('selected', ACCENT)])
        st.configure('TButton', background='#e2e8f0', foreground=TEXT,
                     padding=(10, 5), borderwidth=0, font=FONT)
        st.map('TButton', background=[('active', '#cbd5e1'), ('disabled', '#eef1f6')],
               foreground=[('disabled', '#9aa4b2')])
        st.configure('Accent.TButton', background=ACCENT, foreground='white',
                     font=FONT_B, padding=(12, 6))
        st.map('Accent.TButton', background=[('active', ACCENT_DARK), ('disabled', '#94a3b8')])
        st.configure('Treeview', background=CARD, fieldbackground=CARD,
                     rowheight=27, borderwidth=0, font=FONT_S)
        st.configure('Treeview.Heading', background='#e8edf5', foreground=TEXT,
                     font=FONT_B, padding=(4, 5), borderwidth=0)
        st.map('Treeview', background=[('selected', '#dbeafe')],
               foreground=[('selected', TEXT)])
        st.map('Treeview.Heading', background=[('active', '#dde4f0')])
        st.configure('TCombobox', fieldbackground=CARD, background='#e2e8f0',
                     arrowcolor=ACCENT, borderwidth=1)
        st.configure('TCheckbutton', background=BG, foreground=TEXT)
        st.map('TCheckbutton', background=[('active', BG)])
        st.configure('TRadiobutton', background=BG, foreground=TEXT)
        st.map('TRadiobutton', background=[('active', BG)])
        st.configure('TSpinbox', fieldbackground=CARD, background='#e2e8f0',
                     arrowcolor=ACCENT, borderwidth=1)
        st.configure('TEntry', fieldbackground=CARD, borderwidth=1)
        st.configure('Horizontal.TProgressbar', background=ACCENT,
                     troughcolor='#e2e8f0', borderwidth=0, thickness=10)
        st.configure('TSeparator', background='#cbd5e1')
        st.configure('Hint.TLabel', foreground=SUB, background=BG, font=FONT_S)
        st.configure('Warn.TLabel', foreground=BADC, background=BG)
        st.configure('Ok.TLabel', foreground=OKC, background=BG)
        st.configure('Title.TLabel', foreground=ACCENT_DARK, background=BG,
                     font=('Microsoft YaHei UI', 11, 'bold'))

    # ================= 头部（与界面统一的浅色设计） =================
    def _build_banner(self):
        self.header = tk.Frame(self.root, bg=CARD)
        self.header.pack(fill='x', side='top')
        # 底部品牌渐变分隔线（细，呼应强调色，不突兀）
        self.divider = tk.Canvas(self.header, height=3, highlightthickness=0, bg=CARD)
        self.divider.pack(side='bottom', fill='x')
        self.divider.bind('<Configure>', lambda e: self._draw_divider())
        row = tk.Frame(self.header, bg=CARD)
        row.pack(fill='x', padx=18, pady=12)
        # 左侧：电视图标 + 标题/标语
        self._header_icon = None
        ico = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
                           'icon_44.png')
        if os.path.exists(ico):
            try:
                self._header_icon = tk.PhotoImage(file=ico)
                tk.Label(row, image=self._header_icon, bg=CARD).pack(side='left', padx=(0, 14))
            except tk.TclError:
                self._header_icon = None
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side='left')
        tk.Label(txt, text=APP_NAME, font=('Microsoft YaHei UI', 18, 'bold'),
                 fg=TEXT, bg=CARD).pack(anchor='w')
        tk.Label(txt, text='全国组播直播源 · 抓包分析 · 频道验证 · 一键生成 M3U',
                 font=FONT_S, fg=SUB, bg=CARD).pack(anchor='w', pady=(2, 0))
        # 右侧：作者 / QQ群 / 版本
        right = tk.Frame(row, bg=CARD)
        right.pack(side='right')
        self._header_link(right, '作者：锤无双 ↗', AUTHOR_URL).pack(anchor='e')
        self._header_link(right, 'QQ群：%s（点击复制）' % QQ_GROUP, None,
                          copy=QQ_GROUP).pack(anchor='e', pady=(3, 0))
        tk.Label(right, text='v%s · 单文件绿色版' % APP_VER, font=FONT_S,
                 fg='#9aa4b2', bg=CARD).pack(anchor='e', pady=(3, 0))
        self._draw_divider()

    def _header_link(self, parent, text, url, copy=None):
        lbl = tk.Label(parent, text=text, font=FONT_S, fg=ACCENT, bg=CARD, cursor='hand2')

        def click(_e):
            if url:
                webbrowser.open(url)
            elif copy:
                self.root.clipboard_clear()
                self.root.clipboard_append(copy)
                old = lbl.cget('text')
                lbl.config(text='✓ 已复制群号 %s' % copy, fg=OKC)
                self.root.after(1500, lambda: lbl.config(text=old, fg=ACCENT))
        lbl.bind('<Button-1>', click)
        return lbl

    def _draw_divider(self):
        c = self.divider
        c.delete('all')
        w = max(c.winfo_width(), 800)
        c1 = (37, 99, 235)
        c2 = (125, 170, 250)
        for x in range(w):
            t = x / max(w - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            c.create_line(x, 0, x, 3, fill='#%02x%02x%02x' % (r, g, b))

    # ================= 菜单/状态栏 =================
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label='保存配置与频道列表', command=self._save_cfg)
        m.add_command(label='打开程序目录', command=lambda: os.startfile(app_dir()))
        m.add_separator()
        m.add_command(label='退出', command=self._on_close)
        menubar.add_cascade(label='文件', menu=m)
        t = tk.Menu(menubar, tearoff=0)
        t.add_command(label='刷新网卡列表', command=self._refresh_ifaces)
        t.add_command(label='运行自测', command=self._run_selftest)
        menubar.add_cascade(label='工具', menu=t)
        h = tk.Menu(menubar, tearoff=0)
        h.add_command(label='视频教程（B站）', command=lambda: webbrowser.open(TUTORIAL_URL))
        h.add_command(label='作者主页（B站-锤无双）', command=lambda: webbrowser.open(AUTHOR_URL))
        h.add_command(label='关于', command=lambda: self.nb.select(self.tab_help))
        menubar.add_cascade(label='帮助', menu=h)
        self.root.config(menu=menubar)

    def _build_status(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill='x', side='bottom', padx=8, pady=4)
        self.status_lbl = ttk.Label(bar, text='', style='Hint.TLabel')
        self.status_lbl.pack(side='left')
        ttk.Label(bar, text='作者：锤无双 · QQ群 %s' % QQ_GROUP, style='Hint.TLabel').pack(side='right')
        self._update_status()

    def _update_status(self):
        admin = '管理员✓' if netutil.is_admin() else '⚠非管理员(抓包需管理员)'
        pk = 'pktmon✓' if self.pktmon.available() else '⚠pktmon不可用(需Win10 1809+)'
        wired = [i['ipv4'] for i in self.ifaces if i['kind'] == 'wired' and i['ipv4']]
        wifi = [i['ipv4'] for i in self.ifaces if i['kind'] == 'wifi' and i['ipv4']]
        okc = sum(1 for c in self.channels if c.get('ok'))
        self.status_lbl.config(text='%s | %s | 有线:%s | WiFi:%s | 频道 %d (可用 %d)'
                               % (admin, pk, ','.join(wired) or '无',
                                  ','.join(wifi) or '无', len(self.channels), okc))

    def _log(self, msg):
        self.q.put(('log', msg))

    # ================= 向导页 =================
    def _build_wizard(self):
        self.tab_wiz = ttk.Frame(self.nb)
        self.nb.add(self.tab_wiz, text=' ① 接线向导 ')
        pw = ttk.PanedWindow(self.tab_wiz, orient='horizontal')
        pw.pack(fill='both', expand=True, padx=4, pady=4)
        left = ttk.Frame(pw)
        pw.add(left, weight=2)
        ttk.Label(left, text='硬件情况问卷（如实选择，生成专属接线指导）',
                  style='Title.TLabel').pack(anchor='w', pady=(4, 6))
        cv = tk.Canvas(left, highlightthickness=0, bg=BG)
        sb = ttk.Scrollbar(left, orient='vertical', command=cv.yview)
        self.wiz_form = ttk.Frame(cv)
        self.wiz_form.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all')))
        cv.create_window((0, 0), window=self.wiz_form, anchor='nw')
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        def _wheel(e):
            cv.yview_scroll(-1 * (e.delta // 120), 'units')
        cv.bind('<Enter>', lambda e: cv.bind_all('<MouseWheel>', _wheel))
        cv.bind('<Leave>', lambda e: cv.unbind_all('<MouseWheel>'))
        cv.bind('<Configure>', lambda e: cv.itemconfigure('all', width=e.width))
        self.wiz_vars = {}
        for q in wizard.QUESTIONS:
            qf = ttk.LabelFrame(self.wiz_form, text=q['text'])
            qf.pack(fill='x', padx=4, pady=4)
            var = tk.StringVar(value=self.cfg['wizard'].get(q['id'], q['options'][0][0]))
            self.wiz_vars[q['id']] = var
            for val, label in q['options']:
                ttk.Radiobutton(qf, text=label, value=val, variable=var).pack(anchor='w', padx=8, pady=1)
        ttk.Button(left, text='生成接线指导 →', style='Accent.TButton',
                   command=self._gen_wiz_plan).pack(fill='x', padx=4, pady=8)
        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        self.wiz_msg = ttk.Label(right, text='', style='Warn.TLabel', wraplength=580, justify='left')
        self.wiz_msg.pack(fill='x', padx=4, pady=(4, 2))
        mid = ttk.Frame(right)
        mid.pack(fill='both', expand=True, padx=4)
        lf = ttk.Frame(mid)
        lf.pack(side='left', fill='both', expand=True)
        ttk.Label(lf, text='接线步骤（点击查看详情）', style='Title.TLabel').pack(anchor='w')
        self.wiz_steps_lb = tk.Listbox(lf, height=8, activestyle='none', bg=CARD, fg=TEXT,
                                       selectbackground='#dbeafe', selectforeground=TEXT,
                                       font=FONT, exportselection=False, relief='solid', bd=1,
                                       highlightthickness=0)
        self.wiz_steps_lb.pack(fill='both', expand=True, pady=2)
        self.wiz_steps_lb.bind('<<ListboxSelect>>', self._wiz_step_sel)
        nav = ttk.Frame(lf)
        nav.pack(fill='x')
        ttk.Button(nav, text='上一步', command=lambda: self._wiz_step_move(-1)).pack(side='left', padx=2)
        ttk.Button(nav, text='下一步', command=lambda: self._wiz_step_move(1)).pack(side='left', padx=2)
        ttk.Button(nav, text='完成，去抓包 →', style='Accent.TButton',
                   command=lambda: self.nb.select(self.tab_cap)).pack(side='right', padx=2)
        self.wiz_detail = tk.Text(mid, width=34, height=10, wrap='word', font=FONT,
                                  bg='#fffef5', fg=TEXT, relief='solid', bd=1, highlightthickness=0)
        self.wiz_detail.pack(side='right', fill='both', padx=(6, 0))
        self.wiz_detail.configure(state='disabled')
        self.wiz_canvas = tk.Canvas(right, height=250, bg='white', highlightthickness=1,
                                    highlightbackground='#cbd5e1')
        self.wiz_canvas.pack(fill='x', padx=4, pady=4)
        self.wiz_plan = None
        self.wiz_steps = []
        self.wiz_step_idx = 0
        self._gen_wiz_plan()

    def _gen_wiz_plan(self):
        ans = {k: v.get() for k, v in self.wiz_vars.items()}
        self.cfg['wizard'] = ans
        plan = wizard.build_plan(ans)
        self.wiz_plan = plan
        msgs = []
        if plan['blockers']:
            msgs.append('⛔ 无法继续：\n' + '\n'.join('· ' + b for b in plan['blockers']))
        if plan['warnings']:
            msgs.append('⚠ 注意：\n' + '\n'.join('· ' + w for w in plan['warnings']))
        self.wiz_msg.config(text='\n\n'.join(msgs),
                            style='Warn.TLabel' if plan['blockers'] else 'TLabel')
        self.wiz_steps = plan['steps'] + plan.get('bridge_steps', [])
        self.wiz_steps_lb.delete(0, 'end')
        for s in self.wiz_steps:
            self.wiz_steps_lb.insert('end', s['title'])
        self.wiz_step_idx = 0
        if self.wiz_steps:
            self.wiz_steps_lb.selection_set(0)
            self._show_wiz_step(0)
        else:
            self._set_wiz_detail('请先解决上方 ⛔ 问题。')
        self._draw_topology()

    def _wiz_step_sel(self, _evt=None):
        sel = self.wiz_steps_lb.curselection()
        if sel:
            self._show_wiz_step(sel[0])

    def _wiz_step_move(self, d):
        if not self.wiz_steps:
            return
        i = max(0, min(len(self.wiz_steps) - 1, self.wiz_step_idx + d))
        self.wiz_steps_lb.selection_clear(0, 'end')
        self.wiz_steps_lb.selection_set(i)
        self.wiz_steps_lb.see(i)
        self._show_wiz_step(i)

    def _show_wiz_step(self, i):
        self.wiz_step_idx = i
        s = self.wiz_steps[i]
        self._set_wiz_detail('【%s】\n\n%s' % (s['title'], s['detail']))
        self._draw_topology()

    def _set_wiz_detail(self, txt):
        self.wiz_detail.configure(state='normal')
        self.wiz_detail.delete('1.0', 'end')
        self.wiz_detail.insert('1.0', txt)
        self.wiz_detail.configure(state='disabled')

    def _draw_topology(self):
        c = self.wiz_canvas
        c.delete('all')
        plan = self.wiz_plan or {}
        topo = plan.get('topology', 'none')
        if topo == 'none':
            c.create_text(280, 120, text='（解决 ⛔ 问题后显示拓扑图）', fill='#999999', font=FONT)
            return
        ont = plan.get('ont_label', '光猫 ITV 口')

        def box(x, y, w, h, title, sub='', fill='#eef4ff'):
            c.create_rectangle(x, y, x + w, y + h, fill=fill, outline='#4a6fa5', width=2)
            c.create_text(x + w / 2, y + 16, text=title, font=('Microsoft YaHei UI', 9, 'bold'))
            if sub:
                c.create_text(x + w / 2, y + 36, text=sub, font=('Microsoft YaHei UI', 8), fill='#444')

        def line(x1, y1, x2, y2, color='#4a6fa5', dash=None, label='', lx=0, ly=0, width=2):
            c.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash)
            if label:
                c.create_text((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, text=label,
                              font=('Microsoft YaHei UI', 8), fill=color)

        if topo == 'router':
            igmp = self.wiz_vars.get('router_igmp') and self.wiz_vars['router_igmp'].get() == 'yes'
            box(20, 20, 140, 70, '光猫', 'ITV / 上网口')
            box(230, 20, 180, 90, '路由器', 'WAN · IPTV口 · LAN口')
            box(470, 20, 120, 60, '机顶盒', '接 IPTV 口')
            box(20, 170, 150, 70, '电脑', '接普通 LAN 口')
            line(160, 55, 230, 55, '#0a7a0a', label='单线复用/VLAN', ly=-10)
            line(410, 50, 470, 50, '#4a6fa5', label='IPTV口', ly=-10)
            line(95, 170, 280, 110, '#0a7a0a', label='LAN口', lx=-30)
            if igmp:
                line(320, 110, 320, 170, '#0a7a0a', dash=(4, 3), label='组播转发→LAN', lx=70)
                c.create_text(300, 245, text='已开组播转发：电脑在普通 LAN 口即可抓包/验证，免交换机',
                              font=('Microsoft YaHei UI', 8), fill='#0a7a0a')
            else:
                c.create_text(300, 245, text='未开组播转发：电脑需接 IPTV 绑定口，或在该口下接交换机',
                              font=('Microsoft YaHei UI', 8), fill='#d97706')
            return

        box(20, 20, 150, 70, '光猫', ont + ' / 上网口')
        box(240, 20, 160, 90, '傻瓜交换机', '口1  口2  口3  口4')
        box(470, 20, 120, 60, '机顶盒', '网口', fill='#f5f5f5' if topo == 'merged' else '#eef4ff')
        box(20, 170, 150, 70, '电脑', '有线口 + WiFi')
        box(470, 170, 120, 70, '路由器', 'WAN / LAN / WiFi')
        idx = self.wiz_step_idx
        hi = '#d97706'
        merged = topo == 'merged'
        line(170, 45, 240, 45, hi if (not merged and idx == 2) else '#0a7a0a',
             label='ITV信号线', ly=-10)
        line(470, 50, 400, 50, hi if (not merged and idx == 3) else ('#bbbbbb' if merged else '#4a6fa5'),
             dash=(4, 3) if merged else None, label='退役备用' if merged else '网线', ly=-10)
        line(95, 170, 280, 110, hi if (not merged and idx == 4) else '#0a7a0a', label='有线口', lx=-30)
        line(400, 95, 510, 170, '#0a7a0a' if merged else '#999999',
             dash=None if merged else (4, 3),
             label='桥接线(合并两网)' if merged else '可选桥接线', lx=36, ly=6)
        line(170, 75, 470, 200, '#888888', dash=(2, 3), label='上网线(保持不动)', lx=-60, ly=16)
        line(170, 215, 470, 215, hi if (not merged and idx == 5) else '#888888',
             dash=(2, 3), label='WiFi 上网', ly=-10)
        c.create_text(300, 245, text='绿色=已接/应接  橙色=当前步骤  虚线=无线/可选',
                      font=('Microsoft YaHei UI', 8), fill='#666666')

    # ================= 抓包页 =================
    def _build_capture(self):
        self.tab_cap = ttk.Frame(self.nb)
        self.nb.add(self.tab_cap, text=' ② 抓包分析 ')
        top = ttk.LabelFrame(self.tab_cap, text='抓包控制（Windows 内置 pktmon，无需安装任何驱动）')
        top.pack(fill='x', padx=6, pady=6)
        r1 = ttk.Frame(top)
        r1.pack(fill='x', padx=6, pady=4)
        self.cap_start_btn = ttk.Button(r1, text='▶ 开始抓包', style='Accent.TButton', command=self._cap_start)
        self.cap_start_btn.pack(side='left', padx=4)
        self.cap_stop_btn = ttk.Button(r1, text='■ 停止并分析', style='Accent.TButton',
                                       command=self._cap_stop, state='disabled')
        self.cap_stop_btn.pack(side='left', padx=4)
        ttk.Button(r1, text='导入 pcap/pcapng/etl…', command=self._cap_import).pack(side='left', padx=4)
        ttk.Label(r1, text='自动停止(秒,0=手动):').pack(side='left', padx=(16, 2))
        self.auto_stop_var = tk.IntVar(value=self.cfg.get('auto_stop_sec', 90))
        ttk.Spinbox(r1, from_=0, to=3600, increment=10, textvariable=self.auto_stop_var, width=6).pack(side='left')
        self.keep_pcap_var = tk.BooleanVar(value=self.cfg.get('keep_pcap', False))
        ttk.Checkbutton(r1, text='分析后保留 pcap', variable=self.keep_pcap_var).pack(side='left', padx=12)
        self.cap_state_lbl = ttk.Label(top, text='就绪。开始抓包后：机顶盒开机重启，或遥控器逐个换台（每频道停 3~5 秒）。',
                                       style='Hint.TLabel', wraplength=1050, justify='left')
        self.cap_state_lbl.pack(fill='x', padx=6, pady=(0, 4))
        self.cap_stb_lbl = ttk.Label(top, text='', style='Hint.TLabel')
        self.cap_stb_lbl.pack(fill='x', padx=6, pady=(0, 4))
        cols = ('group', 'port', 'proto', 'pkts', 'bytes', 'dur', 'src', 'igmp', 'ref', 'note')
        heads = ('组播地址', '端口', '封装', '包数', '流量', '时长', '源IP', 'IGMP加组', '参考库名', '备注')
        widths = (125, 55, 45, 70, 80, 60, 115, 65, 130, 90)
        tf = ttk.Frame(self.tab_cap)
        tf.pack(fill='both', expand=True, padx=6, pady=(0, 4))
        self.cap_tree = self._make_tree(tf, cols, heads, widths)
        bf = ttk.Frame(self.tab_cap)
        bf.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Button(bf, text='加入频道列表（选中）', style='Accent.TButton',
                   command=lambda: self._cap_add(False)).pack(side='left', padx=4)
        ttk.Button(bf, text='全部加入（除噪声）', command=lambda: self._cap_add(True)).pack(side='left', padx=4)
        ttk.Button(bf, text='清空结果', command=lambda: self.cap_tree.delete(*self.cap_tree.get_children())).pack(side='left', padx=4)
        ttk.Label(bf, text='噪声=SSDP/mDNS/LLMNR 等局域网协议，不是电视频道', style='Hint.TLabel').pack(side='right')

    def _make_tree(self, parent, cols, heads, widths):
        tree = ttk.Treeview(parent, columns=cols, show='headings', selectmode='extended')
        for col, head, w in zip(cols, heads, widths):
            tree.heading(col, text=head)
            tree.column(col, width=w, anchor='w')
        vsb = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        tree.tag_configure('odd', background='#f7f9fd')
        tree.tag_configure('ok', foreground=OKC)
        tree.tag_configure('bad', foreground=BADC)
        return tree

    def _cap_start(self):
        if not netutil.is_admin():
            messagebox.showerror(APP_NAME, '抓包需要管理员权限。\n请右键本程序 → 以管理员身份运行。')
            return
        if not self.pktmon.available():
            messagebox.showerror(APP_NAME, '未找到 pktmon。需要 Windows 10 1809+ 或 Windows 11。')
            return
        if self.cap_thread and self.cap_thread.is_alive():
            return
        self.cap_start_btn.config(state='disabled')
        self.cap_state_lbl.config(text='正在启动 pktmon…')

        def work():
            ok, msg = self.pktmon.start()
            self.q.put(('cap_started', ok, msg))
        self.cap_thread = threading.Thread(target=work, daemon=True)
        self.cap_thread.start()

    def _cap_stop(self):
        if not self.pktmon.running or self.cap_stopping:
            return
        self.cap_stopping = True
        self.cap_stop_btn.config(state='disabled')
        self.cap_state_lbl.config(text='正在停止抓包并转换格式（大文件可能需要 1~2 分钟）…')

        def work():
            ok, msg = self.pktmon.stop()
            if not ok:
                self.q.put(('cap_error', msg))
                return
            ok, pcap = self.pktmon.convert()
            if not ok:
                self.q.put(('cap_error', pcap))
                return
            self.q.put(('cap_analyzing',))
            try:
                r = capture.analyze(pcap, progress_cb=lambda n: self.q.put(('cap_progress', n)))
            except Exception as e:
                self.q.put(('cap_error', '分析失败: %s' % e))
                return
            if not self.keep_pcap_var.get():
                self.pktmon.cleanup(keep_pcap=False)
            self.q.put(('cap_done', r))
        self.cap_thread = threading.Thread(target=work, daemon=True)
        self.cap_thread.start()

    def _cap_import(self):
        path = filedialog.askopenfilename(
            title='选择抓包文件', filetypes=[('抓包文件', '*.pcap *.pcapng *.etl'), ('所有文件', '*.*')])
        if not path:
            return
        self.cap_state_lbl.config(text='正在分析 %s …' % os.path.basename(path))

        def work():
            p = path
            if path.lower().endswith('.etl'):
                pm = capture.Pktmon(os.path.dirname(path))
                pm.etl = path
                pm.pcap = path + '.pcap'
                ok, p = pm.convert()
                if not ok:
                    self.q.put(('cap_error', p))
                    return
            try:
                r = capture.analyze(p, progress_cb=lambda n: self.q.put(('cap_progress', n)))
            except Exception as e:
                self.q.put(('cap_error', '分析失败: %s' % e))
                return
            self.q.put(('cap_done', r))
        threading.Thread(target=work, daemon=True).start()

    def _cap_show_result(self, r):
        self.cap_tree.delete(*self.cap_tree.get_children())
        self.cap_flows = r['flows']
        self.cap_joins = r['joins']
        common_port = 5140
        real = [f for f in r['flows'] if not f['noise']]
        if real:
            ports = {}
            for f in real:
                ports[f['port']] = ports.get(f['port'], 0) + f['pkts']
            common_port = max(ports, key=ports.get)
        self._cap_common_port = common_port
        for i, f in enumerate(r['flows']):
            ref = channeldb.lookup(f['group'], f['port'])
            mb = f['bytes'] / 1048576
            dur = f['last'] - f['first']
            note = '噪声' if f['noise'] else ('参考✓' if ref and ref.get('ok') else ('参考✗' if ref else ''))
            tags = ('odd',) if i % 2 else ()
            self.cap_tree.insert('', 'end', iid='%s:%d' % (f['group'], f['port']),
                                 values=(f['group'], f['port'], f['proto'], f['pkts'],
                                         '%.1f MB' % mb, '%.0fs' % dur,
                                         ','.join(f['srcs'][:2]), r['joins'].get(f['group'], 0),
                                         ref['name'] if ref else '', note), tags=tags)
        flow_groups = {f['group'] for f in r['flows']}
        for g, cnt in r['joins'].items():
            if g not in flow_groups and not g.startswith('224.0.0.'):
                ref = channeldb.lookup(g, common_port)
                self.cap_tree.insert('', 'end', iid='%s:%d?' % (g, common_port),
                                     values=(g, '%d?' % common_port, '-', 0, '0', '-', '-', cnt,
                                             ref['name'] if ref else '', '仅IGMP,端口推测'))
        st = r['stats']
        stb = r.get('stb')
        txt = '分析完成：总包 %d，去重后 %d，时长 %.0f 秒；发现组播流 %d 条（噪声 %d），IGMP 加组 %d 个。' % (
            st['packets'], st['unique'], st['duration'], len(real),
            len(r['flows']) - len(real), len(r['joins']))
        self.cap_state_lbl.config(text=txt + '  → 选中后「加入频道列表」，再到 ③ 验证。')
        if stb:
            self.cap_stb_lbl.config(text='机顶盒信息(仅本机显示): MAC %s | IP %s | 账号 %s | STBID %s' % (
                stb.get('mac', '?'), stb.get('ip', '?'), stb.get('account', '?'),
                stb.get('hostname', '?')))
        self._update_status()

    def _cap_add(self, all_rows):
        if all_rows:
            items = [i for i in self.cap_tree.get_children()
                     if '噪声' not in self.cap_tree.set(i, 'note')]
        else:
            items = list(self.cap_tree.selection())
        if not items:
            messagebox.showinfo(APP_NAME, '请先在结果表中选择要加入的行。')
            return
        added = 0
        for iid in items:
            vals = self.cap_tree.item(iid, 'values')
            g = vals[0]
            port = int(str(vals[1]).rstrip('?'))
            ref = channeldb.lookup(g, port)
            name = ref['name'] if ref else '未知频道(%s)' % g
            cat = ref['cat'] if ref else '未分类'
            ch = {'name': name, 'group': g, 'port': port, 'cat': cat, 'ok': False,
                  'video': None, 'audio': None, 'res': None, 'sdt_name': '',
                  'source': 'cap', 'ref_ok': ref.get('ok') if ref else None}
            if not any(c['group'] == g and c['port'] == port for c in self.channels):
                self.channels.append(ch)
                added += 1
        self._reload_channel_tree()
        self._save_cfg()
        self._update_status()
        messagebox.showinfo(APP_NAME, '已加入 %d 个频道（重复自动跳过）。\n请到「③ 频道验证」页实测并命名。' % added)
        self.nb.select(self.tab_ver)

    # ================= 验证页 =================
    def _build_verify(self):
        self.tab_ver = ttk.Frame(self.nb)
        self.nb.add(self.tab_ver, text=' ③ 频道验证 ')
        top = ttk.LabelFrame(self.tab_ver, text='验证设置（原生加组收流解析，无需 ffmpeg）')
        top.pack(fill='x', padx=6, pady=6)
        r = ttk.Frame(top)
        r.pack(fill='x', padx=6, pady=4)
        ttk.Label(r, text='组播网卡:').pack(side='left')
        self.ver_iface_cb = ttk.Combobox(r, width=42, state='readonly')
        self.ver_iface_cb.pack(side='left', padx=4)
        ttk.Label(r, text='并发:').pack(side='left', padx=(12, 2))
        self.ver_conc_var = tk.IntVar(value=self.cfg.get('verify_concurrency', 4))
        ttk.Spinbox(r, from_=1, to=8, textvariable=self.ver_conc_var, width=4).pack(side='left')
        ttk.Label(r, text='超时(秒):').pack(side='left', padx=(12, 2))
        self.ver_timeout_var = tk.IntVar(value=self.cfg.get('verify_timeout', 5))
        ttk.Spinbox(r, from_=2, to=20, textvariable=self.ver_timeout_var, width=4).pack(side='left')
        r2 = ttk.Frame(top)
        r2.pack(fill='x', padx=6, pady=(0, 4))
        self.ver_start_btn = ttk.Button(r2, text='验证全部', style='Accent.TButton', command=lambda: self._verify(False))
        self.ver_start_btn.pack(side='left', padx=4)
        ttk.Button(r2, text='验证选中', command=lambda: self._verify(True)).pack(side='left', padx=4)
        self.ver_stop_btn = ttk.Button(r2, text='停止', command=self.ver_stop.set, state='disabled')
        self.ver_stop_btn.pack(side='left', padx=4)
        ttk.Separator(r2, orient='vertical').pack(side='left', fill='y', padx=8)
        ttk.Button(r2, text='📚 选择地区载入参考库', style='Accent.TButton', command=self._load_ref).pack(side='left', padx=4)
        self.upd_btn = ttk.Button(r2, text='🔄 在线更新参考库', command=self._update_refdb)
        self.upd_btn.pack(side='left', padx=4)
        ttk.Button(r2, text='导入参考库文件', command=self._import_refdb).pack(side='left', padx=4)
        r3 = ttk.Frame(top)
        r3.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Button(r3, text='导入 M3U…', command=self._import_m3u).pack(side='left', padx=4)
        ttk.Button(r3, text='手动添加', command=self._add_manual).pack(side='left', padx=4)
        ttk.Button(r3, text='删除选中', command=self._del_selected).pack(side='left', padx=4)
        self.db_lbl = ttk.Label(r3, text='', style='Hint.TLabel')
        self.db_lbl.pack(side='right', padx=6)
        self._refresh_db_lbl()
        self.ver_prog = ttk.Progressbar(top, mode='determinate')
        self.ver_prog.pack(fill='x', padx=6, pady=(0, 2))
        self.ver_prog_lbl = ttk.Label(top, text='提示：验证=真实加入组播组收流。抓包搭线阶段用有线口(169.254.x 也可)；已桥接网络用有线口(192.168.x)。',
                                      style='Hint.TLabel', wraplength=1050, justify='left')
        self.ver_prog_lbl.pack(fill='x', padx=6, pady=(0, 4))
        cols = ('name', 'group', 'port', 'cat', 'status', 'video', 'audio', 'res', 'sdt', 'src')
        heads = ('频道名', '组播地址', '端口', '分类', '状态', '视频', '音频', '分辨率', 'SDT名', '来源')
        widths = (150, 125, 55, 85, 85, 60, 60, 80, 120, 55)
        tf = ttk.Frame(self.tab_ver)
        tf.pack(fill='both', expand=True, padx=6, pady=(0, 4))
        self.ver_tree = self._make_tree(tf, cols, heads, widths)
        self.ver_tree.bind('<Double-1>', lambda e: self._edit_selected())
        bf = ttk.Frame(self.tab_ver)
        bf.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Button(bf, text='重命名/编辑选中', command=self._edit_selected).pack(side='left', padx=4)
        ttk.Button(bf, text='复制组播地址', command=self._copy_addr).pack(side='left', padx=4)
        ttk.Label(bf, text='双击行可编辑；验证后自动解析 SDT 频道名（未命名频道）', style='Hint.TLabel').pack(side='right')

    def _refresh_db_lbl(self):
        info = channeldb.db_info()
        self.db_lbl.config(text='参考库：%s · %s · %d省 %d列表 %d频道' % (
            info['updated'], info['origin'], info['provinces'], info['regions'], info['channels']))

    def _iface_labels(self):
        out = []
        for i in self.ifaces:
            if not i['ipv4']:
                continue
            kind = '有线' if i['kind'] == 'wired' else ('WiFi' if i['kind'] == 'wifi' else '其他')
            out.append('%s | %s | %s%s' % (i['ipv4'], kind, i['name'],
                                           (' | 网关 ' + i['gateway']) if i['gateway'] else ' | 无网关'))
        return out

    def _refresh_iface_widgets(self):
        labels = self._iface_labels()
        for cb in (getattr(self, 'ver_iface_cb', None), getattr(self, 'prox_iface_cb', None)):
            if cb is None:
                continue
            cb['values'] = labels
            pref = netutil.pick_multicast_iface(self.ifaces)
            sel = next((l for l in labels if l.startswith(pref + ' |')), labels[0] if labels else '')
            if sel:
                cb.set(sel)

    def _refresh_ifaces(self):
        self.ifaces = netutil.list_interfaces()
        self._refresh_iface_widgets()
        self._update_status()

    def _selected_iface_ip(self, cb):
        v = cb.get()
        return v.split(' | ')[0] if v else ''

    def _reload_channel_tree(self):
        self.ver_tree.delete(*self.ver_tree.get_children())
        for i, ch in enumerate(m3u.sort_channels(self.channels)):
            self._insert_channel_row(ch, i)

    def _insert_channel_row(self, ch, idx=None):
        iid = '%s:%d' % (ch['group'], ch['port'])
        status = '✓ 可用' if ch.get('ok') else ('✗ 不可用' if ch.get('tested') else '未验证')
        src = {'cap': '抓包', 'ref': '参考库', 'import': '导入', 'manual': '手动'}.get(ch.get('source'), '')
        vals = (ch.get('name', ''), ch['group'], ch['port'], ch.get('cat', ''), status,
                ch.get('video') or '', ch.get('audio') or '', ch.get('res') or '',
                ch.get('sdt_name') or '', src)
        tags = []
        if ch.get('ok'):
            tags.append('ok')
        elif ch.get('tested'):
            tags.append('bad')
        exists = self.ver_tree.exists(iid)
        if idx is None:
            idx = self.ver_tree.index(iid) if exists else len(self.ver_tree.get_children())
        if idx % 2:
            tags.append('odd')
        if exists:
            self.ver_tree.item(iid, values=vals, tags=tags)
        else:
            self.ver_tree.insert('', 'end', iid=iid, values=vals, tags=tags)

    def _find_ch(self, iid):
        g, p = iid.rsplit(':', 1)
        for c in self.channels:
            if c['group'] == g and c['port'] == int(p):
                return c
        return None

    def _load_ref(self):
        d = RefDialog(self.root, self.cfg.get('last_province', ''), self.cfg.get('last_carrier', ''))
        if not d.result:
            return
        prov, carrier = d.result
        self.cfg['last_province'] = prov
        self.cfg['last_carrier'] = carrier
        refs = channeldb.channels_for(prov, carrier)
        added = 0
        for ch in refs:
            if not any(c['group'] == ch['group'] and c['port'] == ch['port'] for c in self.channels):
                self.channels.append(ch)
                added += 1
        self._reload_channel_tree()
        self._save_cfg()
        self._update_status()
        messagebox.showinfo(APP_NAME, '已载入「%s%s」参考列表：新增 %d 个频道。\n点「验证全部」实测可用性。' % (prov, carrier, added))

    def _update_refdb(self):
        if self.upd_thread and self.upd_thread.is_alive():
            return
        if not messagebox.askyesno(APP_NAME,
                                   '从社区开源仓库（xisohi/CHINA-IPTV）拉取最新全国参考库？\n\n'
                                   '· 仅在你点击时联网，平时不后台联网\n'
                                   '· 自动尝试国内加速镜像，失败可稍后重试\n'
                                   '· 更新结果保存在程序目录 refdb.json'):
            return
        self.upd_stop.clear()
        self.upd_btn.config(state='disabled')
        self.ver_prog['maximum'] = 100
        self.ver_prog['value'] = 0
        self.ver_prog_lbl.config(text='正在更新参考库…')

        def progress(done, total, text):
            self.q.put(('upd_progress', done, total, text))

        def work():
            ok, msg = refupdate.fetch_online(progress_cb=progress, stop_event=self.upd_stop)
            self.q.put(('upd_done', ok, msg))
        self.upd_thread = threading.Thread(target=work, daemon=True)
        self.upd_thread.start()

    def _import_refdb(self):
        path = filedialog.askopenfilename(
            title='导入参考库文件', filetypes=[('无双参考库', '*.json *.gz'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            msg = refupdate.import_file(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, '导入失败: %s' % e)
            return
        self._refresh_db_lbl()
        messagebox.showinfo(APP_NAME, msg)

    def _import_m3u(self):
        path = filedialog.askopenfilename(title='导入 M3U', filetypes=[('M3U 播放列表', '*.m3u *.m3u8'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            chans = m3u.read_m3u(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, '导入失败: %s' % e)
            return
        self.channels = m3u.merge_channels(self.channels, chans)
        self._reload_channel_tree()
        self._save_cfg()
        self._update_status()
        messagebox.showinfo(APP_NAME, '已导入 %d 个频道（按地址去重合并）。' % len(chans))

    def _add_manual(self):
        d = EditDialog(self.root, '手动添加频道',
                       [('name', '频道名', '新频道'), ('group', '组播地址', '233.50.201.'),
                        ('port', '端口', '5140'), ('cat', '分类', '其他频道')])
        if not d.result:
            return
        try:
            import socket as _s
            _s.inet_aton(d.result['group'])
            port = int(d.result['port'])
        except (ValueError, OSError):
            messagebox.showerror(APP_NAME, '组播地址或端口不合法。')
            return
        ch = {'name': d.result['name'], 'group': d.result['group'], 'port': port,
              'cat': d.result['cat'], 'ok': False, 'source': 'manual', 'user_named': True}
        self.channels = m3u.merge_channels(self.channels, [ch])
        self._reload_channel_tree()
        self._save_cfg()
        self._update_status()

    def _del_selected(self):
        sel = self.ver_tree.selection()
        if not sel:
            return
        keys = set()
        for iid in sel:
            g, p = iid.rsplit(':', 1)
            keys.add((g, int(p)))
        self.channels = [c for c in self.channels if (c['group'], c['port']) not in keys]
        self._reload_channel_tree()
        self._save_cfg()
        self._update_status()

    def _edit_selected(self):
        sel = self.ver_tree.selection()
        if not sel:
            return
        ch = self._find_ch(sel[0])
        if not ch:
            return
        d = EditDialog(self.root, '编辑频道',
                       [('name', '频道名', ''), ('group', '组播地址', ''),
                        ('port', '端口', ''), ('cat', '分类', '')], values=ch)
        if not d.result:
            return
        try:
            import socket as _s
            _s.inet_aton(d.result['group'])
            port = int(d.result['port'])
        except (ValueError, OSError):
            messagebox.showerror(APP_NAME, '组播地址或端口不合法。')
            return
        old_key = (ch['group'], ch['port'])
        ch.update({'name': d.result['name'], 'group': d.result['group'], 'port': port,
                   'cat': d.result['cat'], 'user_named': True, 'user_catted': True})
        if old_key != (ch['group'], ch['port']):
            self.ver_tree.delete(sel[0])
        self._reload_channel_tree()
        self._save_cfg()
        self._maybe_autosave()

    def _copy_addr(self):
        sel = self.ver_tree.selection()
        if not sel:
            return
        ch = self._find_ch(sel[0])
        if ch:
            self.root.clipboard_clear()
            self.root.clipboard_append('udp://@%s:%d' % (ch['group'], ch['port']))

    def _verify(self, selected_only):
        if self.ver_thread and self.ver_thread.is_alive():
            return
        if selected_only:
            chans = [self._find_ch(i) for i in self.ver_tree.selection()]
            chans = [c for c in chans if c]
        else:
            chans = list(self.channels)
        if not chans:
            messagebox.showinfo(APP_NAME, '频道列表为空。先抓包加入、载入参考库或导入 M3U。')
            return
        iface = self._selected_iface_ip(self.ver_iface_cb)
        if not iface:
            messagebox.showerror(APP_NAME, '请选择组播网卡（需要有线口连接 IPTV 网络/桥接后的局域网）。')
            return
        self.ver_stop.clear()
        self.ver_start_btn.config(state='disabled')
        self.ver_stop_btn.config(state='normal')
        self.ver_prog['maximum'] = len(chans)
        self.ver_prog['value'] = 0
        for c in chans:
            c['tested'] = False
            self._insert_channel_row(c)
        conc = self.ver_conc_var.get()
        timeout = self.ver_timeout_var.get()
        self.cfg['verify_concurrency'] = conc
        self.cfg['verify_timeout'] = timeout

        def progress(done, total, ch, r):
            self.q.put(('ver_progress', done, total, ch, r))

        def work():
            verify.verify_batch(chans, iface, concurrency=conc, timeout=timeout,
                                progress_cb=progress, stop_event=self.ver_stop)
            self.q.put(('ver_done',))
        self.ver_thread = threading.Thread(target=work, daemon=True)
        self.ver_thread.start()

    def _apply_ver_result(self, ch, r):
        ch['ok'] = r['ok']
        ch['tested'] = True
        ch['video'] = r['video']
        ch['audio'] = r['audio']
        ch['res'] = r['res']
        ch['sdt_name'] = r['sdt_name']
        if r['ok'] and r['sdt_name'] and not ch.get('user_named'):
            nm = channeldb.normalize_name(r['sdt_name'])
            ref = channeldb.lookup(ch['group'], ch['port'])
            if not ref:
                ch['name'] = nm
                if not ch.get('user_catted'):
                    ch['cat'] = channeldb.guess_category(nm)
        self._insert_channel_row(ch)

    # ================= M3U 页 =================
    def _build_m3u(self):
        self.tab_m3u = ttk.Frame(self.nb)
        self.nb.add(self.tab_m3u, text=' ④ 生成 M3U ')
        top = ttk.LabelFrame(self.tab_m3u, text='输出设置')
        top.pack(fill='x', padx=6, pady=6)
        r1 = ttk.Frame(top)
        r1.pack(fill='x', padx=6, pady=4)
        ttk.Label(r1, text='地址格式:').pack(side='left')
        self.fmt_var = tk.StringVar(value=self.cfg.get('fmt', 'udp'))
        for val, txt in (('udp', 'udp:// 组播直连（主用）'), ('rtp', 'rtp://'),
                         ('udpxy', 'http:// udpxy 转发')):
            ttk.Radiobutton(r1, text=txt, value=val, variable=self.fmt_var).pack(side='left', padx=6)
        r2 = ttk.Frame(top)
        r2.pack(fill='x', padx=6, pady=4)
        ttk.Label(r2, text='udpxy 主机:').pack(side='left')
        self.udpxy_host_var = tk.StringVar(value=self.cfg.get('udpxy_host') or netutil.lan_ip_for_udpxy(self.ifaces))
        ttk.Entry(r2, textvariable=self.udpxy_host_var, width=16).pack(side='left', padx=4)
        ttk.Label(r2, text='端口:').pack(side='left')
        self.udpxy_port_var = tk.IntVar(value=self.cfg.get('udpxy_port', 9999))
        ttk.Spinbox(r2, from_=1, to=65535, textvariable=self.udpxy_port_var, width=7).pack(side='left', padx=4)
        ttk.Button(r2, text='自动填本机IP', command=lambda: self.udpxy_host_var.set(
            netutil.lan_ip_for_udpxy(netutil.list_interfaces()))).pack(side='left', padx=4)
        ttk.Label(r2, text='台标URL前缀(可选):').pack(side='left', padx=(12, 2))
        self.logo_var = tk.StringVar(value=self.cfg.get('logo_base', ''))
        ttk.Entry(r2, textvariable=self.logo_var, width=30).pack(side='left')
        r3 = ttk.Frame(top)
        r3.pack(fill='x', padx=6, pady=4)
        self.only_ok_var = tk.BooleanVar(value=self.cfg.get('only_ok', True))
        ttk.Checkbutton(r3, text='只导出验证可用的频道', variable=self.only_ok_var).pack(side='left', padx=4)
        self.merge_var = tk.BooleanVar(value=self.cfg.get('merge_file', True))
        ttk.Checkbutton(r3, text='与目录中已有文件合并', variable=self.merge_var).pack(side='left', padx=4)
        self.pair_var = tk.BooleanVar(value=self.cfg.get('pair_file', True))
        ttk.Checkbutton(r3, text='同时生成配对格式(udp↔http)', variable=self.pair_var).pack(side='left', padx=4)
        self.autoup_var = tk.BooleanVar(value=self.cfg.get('auto_update', False))
        ttk.Checkbutton(r3, text='频道变化时自动更新文件', variable=self.autoup_var).pack(side='left', padx=4)
        r4 = ttk.Frame(top)
        r4.pack(fill='x', padx=6, pady=4)
        ttk.Label(r4, text='输出目录:').pack(side='left')
        self.outdir_var = tk.StringVar(value=self.cfg.get('out_dir', ''))
        ttk.Entry(r4, textvariable=self.outdir_var).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(r4, text='浏览…', command=self._pick_outdir).pack(side='left', padx=2)
        ttk.Label(r4, text='文件名:').pack(side='left', padx=(8, 2))
        self.outname_var = tk.StringVar(value=self.cfg.get('out_name', 'iptv.m3u'))
        ttk.Entry(r4, textvariable=self.outname_var, width=20).pack(side='left')
        bf = ttk.Frame(self.tab_m3u)
        bf.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Button(bf, text='预览', command=self._preview_m3u).pack(side='left', padx=4)
        ttk.Button(bf, text='💾 保存 / 更新 M3U', style='Accent.TButton', command=self._save_m3u).pack(side='left', padx=4)
        ttk.Button(bf, text='打开输出目录', command=self._open_outdir).pack(side='left', padx=4)
        self.m3u_status = ttk.Label(bf, text='', style='Hint.TLabel')
        self.m3u_status.pack(side='left', padx=12)
        # ---- 推送到 NAS ----
        nf = ttk.LabelFrame(self.tab_m3u, text='推送到 NAS（可选，抓完一键同步播放列表）')
        nf.pack(fill='x', padx=6, pady=(0, 4))
        n1 = ttk.Frame(nf)
        n1.pack(fill='x', padx=6, pady=4)
        ttk.Label(n1, text='方式:').pack(side='left')
        self.nas_method_var = tk.StringVar(value=self.cfg.get('nas_method', 'smb'))
        ttk.Combobox(n1, textvariable=self.nas_method_var, width=16, state='readonly',
                     values=['smb', 'webdav']).pack(side='left', padx=4)
        ttk.Label(n1, text='SMB共享/映射盘:').pack(side='left', padx=(8, 2))
        self.nas_path_var = tk.StringVar(value=self.cfg.get('nas_path', ''))
        ttk.Entry(n1, textvariable=self.nas_path_var).pack(side='left', fill='x', expand=True, padx=4)
        n2 = ttk.Frame(nf)
        n2.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Label(n2, text='WebDAV地址:').pack(side='left')
        self.nas_webdav_var = tk.StringVar(value=self.cfg.get('nas_webdav', ''))
        ttk.Entry(n2, textvariable=self.nas_webdav_var, width=34).pack(side='left', padx=4)
        ttk.Label(n2, text='账号:').pack(side='left', padx=(8, 2))
        self.nas_user_var = tk.StringVar(value=self.cfg.get('nas_user', ''))
        ttk.Entry(n2, textvariable=self.nas_user_var, width=12).pack(side='left')
        ttk.Label(n2, text='密码:').pack(side='left', padx=(8, 2))
        self.nas_pass_var = tk.StringVar(value=self.cfg.get('nas_pass', ''))
        ttk.Entry(n2, textvariable=self.nas_pass_var, width=12, show='*').pack(side='left')
        n3 = ttk.Frame(nf)
        n3.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Button(n3, text='📤 一键推送到 NAS', style='Accent.TButton',
                   command=lambda: self._push_nas(False)).pack(side='left', padx=4)
        self.nas_auto_var = tk.BooleanVar(value=self.cfg.get('nas_auto', False))
        ttk.Checkbutton(n3, text='保存后自动推送', variable=self.nas_auto_var).pack(side='left', padx=8)
        self.nas_status = ttk.Label(n3, text='SMB 填 \\\\NAS\\共享\\iptv 或映射盘；WebDAV 填 http://NAS:5005/目录',
                                    style='Hint.TLabel')
        self.nas_status.pack(side='left', padx=8)
        pf = ttk.LabelFrame(self.tab_m3u, text='预览')
        pf.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        self.m3u_preview = tk.Text(pf, wrap='none', font=MONO, bg='#fbfcfe', fg=TEXT,
                                   relief='solid', bd=1, highlightthickness=0)
        psb = ttk.Scrollbar(pf, orient='vertical', command=self.m3u_preview.yview)
        self.m3u_preview.configure(yscrollcommand=psb.set)
        self.m3u_preview.pack(side='left', fill='both', expand=True)
        psb.pack(side='right', fill='y')

    def _pick_outdir(self):
        d = filedialog.askdirectory(title='选择 M3U 输出目录')
        if d:
            self.outdir_var.set(d)

    def _open_outdir(self):
        d = self.outdir_var.get()
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showinfo(APP_NAME, '请先选择输出目录。')

    def _m3u_params(self):
        return dict(fmt=self.fmt_var.get(), udpxy_host=self.udpxy_host_var.get().strip(),
                    udpxy_port=self.udpxy_port_var.get(), logo_base=self.logo_var.get().strip(),
                    only_ok=self.only_ok_var.get())

    def _collect_cfg_m3u(self):
        self.cfg.update({'fmt': self.fmt_var.get(), 'udpxy_host': self.udpxy_host_var.get(),
                         'udpxy_port': self.udpxy_port_var.get(), 'logo_base': self.logo_var.get(),
                         'only_ok': self.only_ok_var.get(), 'merge_file': self.merge_var.get(),
                         'pair_file': self.pair_var.get(), 'auto_update': self.autoup_var.get(),
                         'out_dir': self.outdir_var.get(), 'out_name': self.outname_var.get(),
                         'nas_method': self.nas_method_var.get(), 'nas_path': self.nas_path_var.get(),
                         'nas_webdav': self.nas_webdav_var.get(), 'nas_user': self.nas_user_var.get(),
                         'nas_pass': self.nas_pass_var.get(), 'nas_auto': self.nas_auto_var.get()})

    def _preview_m3u(self):
        p = self._m3u_params()
        lines = ['#EXTM3U']
        for ch in m3u.sort_channels(self.channels):
            if p['only_ok'] and not ch.get('ok'):
                continue
            name = ch.get('name') or '%s:%d' % (ch['group'], ch['port'])
            lines.append('#EXTINF:-1 tvg-name="%s" group-title="%s",%s' % (name, ch.get('cat') or '未分类', name))
            lines.append(m3u.channel_url(ch, **{k: p[k] for k in ('fmt', 'udpxy_host', 'udpxy_port')}))
        self.m3u_preview.delete('1.0', 'end')
        self.m3u_preview.insert('1.0', '\n'.join(lines))
        self.m3u_status.config(text='预览 %d 个频道（未写入文件）' % ((len(lines) - 1) // 2))

    def _save_m3u(self):
        self._collect_cfg_m3u()
        outdir = self.outdir_var.get().strip()
        name = self.outname_var.get().strip() or 'iptv.m3u'
        if not outdir:
            d = filedialog.askdirectory(title='选择 M3U 输出目录')
            if not d:
                return
            outdir = d
            self.outdir_var.set(d)
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, '无法创建目录: %s' % e)
            return
        path = os.path.join(outdir, name)
        p = self._m3u_params()
        chans = self.channels
        if self.merge_var.get() and os.path.exists(path):
            try:
                old = m3u.read_m3u(path)
                chans = m3u.merge_channels(old, chans)
            except Exception:
                pass
        try:
            n = m3u.write_m3u(path, chans, **p)
            self._saved_paths = [path]
            extra = ''
            if self.pair_var.get():
                base, ext = os.path.splitext(name)
                if p['fmt'] == 'udpxy':
                    p2 = dict(p, fmt='udp')
                    path2 = os.path.join(outdir, base + '-udp' + ext)
                else:
                    p2 = dict(p, fmt='udpxy')
                    path2 = os.path.join(outdir, base + '-http' + ext)
                n2 = m3u.write_m3u(path2, chans, **p2)
                self._saved_paths.append(path2)
                extra = '；配对版 %s (%d)' % (os.path.basename(path2), n2)
        except OSError as e:
            messagebox.showerror(APP_NAME, '写入失败: %s' % e)
            return
        self.last_save = '%s (%d 频道%s)' % (path, n, extra)
        self._save_cfg()
        self._preview_m3u()
        self.m3u_status.config(text='已保存: ' + self.last_save + '  ' + time.strftime('%H:%M:%S'))
        if self.nas_auto_var.get():
            self._push_nas(True)

    def _push_nas(self, silent):
        self._collect_cfg_m3u()
        paths = getattr(self, '_saved_paths', None)
        if not paths:
            # 尚未保存过：先保存再推
            self._save_m3u()
            paths = getattr(self, '_saved_paths', None)
            if not paths:
                return
        method = self.nas_method_var.get()
        target = self.nas_path_var.get().strip() if method == 'smb' else self.nas_webdav_var.get().strip()
        if not target:
            if not silent:
                messagebox.showerror(APP_NAME, '请先填写 NAS 目标（SMB 共享路径或 WebDAV 地址）。')
            return
        results = naspush.push_many(paths, method, target,
                                    self.nas_user_var.get(), self.nas_pass_var.get())
        ok = [d for _, d in results if not str(d).startswith('失败')]
        bad = [d for _, d in results if str(d).startswith('失败')]
        self._save_cfg()
        if bad:
            self.nas_status.config(text='推送部分失败: %s' % bad[0], style='Warn.TLabel')
            if not silent:
                messagebox.showerror(APP_NAME, '推送失败:\n' + '\n'.join(bad))
        else:
            self.nas_status.config(text='已推送 %d 个文件到 NAS ✓' % len(ok), style='Ok.TLabel')
            if not silent:
                messagebox.showinfo(APP_NAME, '已推送到 NAS:\n' + '\n'.join(ok))

    def _maybe_autosave(self):
        if self.autoup_var.get() and self.outdir_var.get().strip():
            try:
                self._save_m3u()
            except Exception:
                pass

    # ================= 转发页 =================
    def _build_proxy(self):
        self.tab_prox = ttk.Frame(self.nb)
        self.nb.add(self.tab_prox, text=' ⑤ 转发服务(可选) ')
        top = ttk.LabelFrame(self.tab_prox, text='组播 → HTTP 单播转发（udpxy 等价，WiFi 设备播放更稳）')
        top.pack(fill='x', padx=6, pady=6)
        r = ttk.Frame(top)
        r.pack(fill='x', padx=6, pady=6)
        ttk.Label(r, text='监听端口:').pack(side='left')
        self.prox_port_var = tk.IntVar(value=self.cfg.get('proxy_port', 9999))
        ttk.Spinbox(r, from_=1, to=65535, textvariable=self.prox_port_var, width=7).pack(side='left', padx=4)
        ttk.Label(r, text='组播网卡:').pack(side='left', padx=(12, 2))
        self.prox_iface_cb = ttk.Combobox(r, width=42, state='readonly')
        self.prox_iface_cb.pack(side='left', padx=4)
        self.prox_start_btn = ttk.Button(r, text='▶ 启动服务', style='Accent.TButton', command=self._prox_start)
        self.prox_start_btn.pack(side='left', padx=8)
        self.prox_stop_btn = ttk.Button(r, text='■ 停止', command=self._prox_stop, state='disabled')
        self.prox_stop_btn.pack(side='left', padx=4)
        self.prox_state_lbl = ttk.Label(top, text='未运行。启动后首次会弹 Windows 防火墙提示，请点「允许(专用网络)」。',
                                        style='Hint.TLabel', wraplength=1050, justify='left')
        self.prox_state_lbl.pack(fill='x', padx=6, pady=(0, 6))
        uf = ttk.LabelFrame(self.tab_prox, text='播放地址（复制到 VLC / Kodi / DIYP / 电视盒子）')
        uf.pack(fill='x', padx=6, pady=6)
        self.prox_url_lbl = ttk.Label(uf, text='', font=MONO, wraplength=1050, justify='left')
        self.prox_url_lbl.pack(fill='x', padx=8, pady=6)
        ttk.Button(uf, text='复制播放列表地址', command=self._prox_copy).pack(anchor='w', padx=8, pady=(0, 8))
        sf = ttk.LabelFrame(self.tab_prox, text='活跃流（每 2 秒刷新）')
        sf.pack(fill='both', expand=True, padx=6, pady=6)
        self.prox_status_txt = tk.Text(sf, height=8, font=MONO, bg='#fbfcfe', fg=TEXT,
                                       state='disabled', relief='solid', bd=1, highlightthickness=0)
        self.prox_status_txt.pack(fill='both', expand=True, padx=4, pady=4)
        ttk.Label(self.tab_prox, text='⚠ 仅限局域网使用，禁止把端口映射到公网。电脑需保持开机；'
                  '需要 7×24 小时服务请考虑 NAS/路由器方案。', style='Warn.TLabel',
                  wraplength=1050, justify='left').pack(fill='x', padx=8, pady=(0, 8))

    def _prox_urls(self):
        lan = netutil.lan_ip_for_udpxy(self.ifaces)
        port = self.prox_port_var.get()
        return ('播放列表: http://%s:%d/playlist.m3u\n'
                '单频道例: http://%s:%d/udp/233.50.201.118:5140\n'
                '状态页:   http://%s:%d/status' % (lan, port, lan, port, lan, port))

    def _prox_start(self):
        if self.proxy_srv and self.proxy_srv.running:
            return
        iface = self._selected_iface_ip(self.prox_iface_cb)
        if not iface:
            messagebox.showerror(APP_NAME, '请选择组播网卡。')
            return
        port = self.prox_port_var.get()
        self.cfg['proxy_port'] = port
        self.proxy_srv = proxy.ProxyServer(iface, port, channels_cb=lambda: self.channels)
        ok, msg = self.proxy_srv.start()
        if ok:
            self.prox_start_btn.config(state='disabled')
            self.prox_stop_btn.config(state='normal')
            self.prox_state_lbl.config(text='运行中: %s' % msg, style='Ok.TLabel')
            self.prox_url_lbl.config(text=self._prox_urls())
        else:
            messagebox.showerror(APP_NAME, msg)

    def _prox_stop(self):
        if self.proxy_srv:
            self.proxy_srv.stop()
        self.prox_start_btn.config(state='normal')
        self.prox_stop_btn.config(state='disabled')
        self.prox_state_lbl.config(text='已停止。', style='Hint.TLabel')

    def _prox_copy(self):
        lan = netutil.lan_ip_for_udpxy(self.ifaces)
        self.root.clipboard_clear()
        self.root.clipboard_append('http://%s:%d/playlist.m3u' % (lan, self.prox_port_var.get()))

    # ================= 帮助/关于页 =================
    def _build_help(self):
        self.tab_help = ttk.Frame(self.nb)
        self.nb.add(self.tab_help, text=' ⑥ 帮助/关于 ')
        about = ttk.LabelFrame(self.tab_help, text='关于')
        about.pack(fill='x', padx=6, pady=6)
        row = ttk.Frame(about)
        row.pack(fill='x', padx=10, pady=6)
        ttk.Label(row, text='%s v%s · 单文件绿色版' % (APP_NAME, APP_VER),
                  font=('Microsoft YaHei UI', 12, 'bold')).pack(side='left')
        links = ttk.Frame(about)
        links.pack(fill='x', padx=10, pady=(0, 8))
        self._link(links, '作者：锤无双 ↗（B站）', AUTHOR_URL).pack(side='left', padx=(0, 24))
        self._link(links, '视频教程 ↗', TUTORIAL_URL).pack(side='left', padx=(0, 24))
        self._link(links, 'QQ群：%s（点击复制）' % QQ_GROUP, None, copy=QQ_GROUP).pack(side='left', padx=(0, 24))
        self._link(links, '开源仓库 ↗', 'https://github.com/chuiziyao/wushuang-iptv').pack(side='left')
        txt = tk.Text(self.tab_help, wrap='word', font=FONT, bg='#fffef8', fg=TEXT,
                      padx=14, pady=10, relief='solid', bd=1, highlightthickness=0)
        sb = ttk.Scrollbar(self.tab_help, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side='left', fill='both', expand=True, padx=(6, 0), pady=(0, 6))
        sb.pack(side='right', fill='y', pady=(0, 6))
        txt.insert('1.0', HELP_TEXT)
        txt.configure(state='disabled')

    def _link(self, parent, text, url, copy=None):
        lbl = tk.Label(parent, text=text, font=FONT, fg=ACCENT, bg=BG,
                       cursor='hand2', underline=0)

        def click(_e):
            if url:
                webbrowser.open(url)
            elif copy:
                self.root.clipboard_clear()
                self.root.clipboard_append(copy)
                old = lbl.cget('text')
                lbl.config(text='✓ 已复制群号 %s' % copy)
                self.root.after(1500, lambda: lbl.config(text=old))
        lbl.bind('<Button-1>', click)
        return lbl

    # ================= 事件循环 =================
    def _poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, ev):
        kind = ev[0]
        if kind == 'log':
            self.cap_state_lbl.config(text=ev[1])
        elif kind == 'cap_started':
            ok, msg = ev[1], ev[2]
            if ok:
                self.cap_started = time.time()
                self.cap_stop_btn.config(state='normal')
                self.cap_state_lbl.config(text='● 抓包中… 请现在操作机顶盒：开机重启，或遥控器逐个换台（每频道停 3~5 秒）。')
            else:
                self.cap_start_btn.config(state='normal')
                messagebox.showerror(APP_NAME, msg)
        elif kind == 'cap_analyzing':
            self.cap_state_lbl.config(text='正在分析抓包文件…')
        elif kind == 'cap_progress':
            self.cap_state_lbl.config(text='正在分析抓包文件… 已读 %d 包' % ev[1])
        elif kind == 'cap_error':
            self.cap_start_btn.config(state='normal')
            self.cap_stop_btn.config(state='disabled')
            self.cap_started = None
            self.cap_stopping = False
            messagebox.showerror(APP_NAME, ev[1])
        elif kind == 'cap_done':
            self.cap_start_btn.config(state='normal')
            self.cap_stop_btn.config(state='disabled')
            self.cap_started = None
            self.cap_stopping = False
            self._cap_show_result(ev[1])
        elif kind == 'ver_progress':
            done, total, ch, r = ev[1], ev[2], ev[3], ev[4]
            self._apply_ver_result(ch, r)
            self.ver_prog['value'] = done
            self.ver_prog_lbl.config(text='验证中 %d/%d：%s → %s' % (
                done, total, ch.get('name'), '✓可用' if r['ok'] else '✗' + (r['error'] or '不可用')))
        elif kind == 'ver_done':
            self.ver_start_btn.config(state='normal')
            self.ver_stop_btn.config(state='disabled')
            okc = sum(1 for c in self.channels if c.get('ok'))
            self.ver_prog_lbl.config(text='验证完成：%d/%d 可用。到「④ 生成 M3U」保存播放列表。' % (okc, len(self.channels)))
            self._save_cfg()
            self._update_status()
            self._maybe_autosave()
        elif kind == 'upd_progress':
            done, total, text = ev[1], ev[2], ev[3]
            self.ver_prog['value'] = int(done * 100 / max(total, 1))
            self.ver_prog_lbl.config(text='更新参考库 %d/%d：%s' % (done, total, text))
        elif kind == 'upd_done':
            ok, msg = ev[1], ev[2]
            self.upd_btn.config(state='normal')
            self.ver_prog['value'] = 0
            self.ver_prog_lbl.config(text=msg)
            self._refresh_db_lbl()
            if ok:
                messagebox.showinfo(APP_NAME, msg)
            else:
                messagebox.showwarning(APP_NAME, msg)

    def _tick(self):
        if self.cap_started and self.pktmon.running:
            el = int(time.time() - self.cap_started)
            auto = self.auto_stop_var.get()
            self.cap_state_lbl.config(text='● 抓包中 %d 秒%s… 请操作机顶盒换台（每频道停 3~5 秒）。' % (
                el, ('，%d 秒后自动停止' % auto) if auto else ''))
            if auto and el >= auto:
                self._cap_stop()
        if self.proxy_srv and self.proxy_srv.running:
            with self.proxy_srv.lock:
                act = dict(self.proxy_srv.active)
            self.prox_status_txt.configure(state='normal')
            self.prox_status_txt.delete('1.0', 'end')
            if act:
                self.prox_status_txt.insert('1.0', '\n'.join('%s  观看数 %d' % (k, v) for k, v in act.items()))
            else:
                self.prox_status_txt.insert('1.0', '（无活跃流）')
            self.prox_status_txt.configure(state='disabled')
        self.root.after(1000, self._tick)

    def _run_selftest(self):
        import subprocess
        args = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'selftest.py')] \
            if not getattr(sys, 'frozen', False) else [sys.executable, '--selftest']
        try:
            r = subprocess.run(args, capture_output=True, timeout=120, creationflags=0x08000000)
            out = (r.stdout or b'').decode('utf-8', 'replace')
            messagebox.showinfo(APP_NAME + ' 自测', out[-3000:] or ('exit=%d' % r.returncode))
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def _on_close(self):
        try:
            if self.proxy_srv and self.proxy_srv.running:
                self.proxy_srv.stop()
            if self.pktmon.running:
                self.pktmon.stop()
            self.ver_stop.set()
            self.upd_stop.set()
            self.cfg['auto_stop_sec'] = self.auto_stop_var.get()
            self.cfg['keep_pcap'] = self.keep_pcap_var.get()
            self._collect_cfg_m3u()
            self._save_cfg()
        except Exception:
            pass
        self.root.destroy()


HELP_TEXT = '''【原理速览】
电信/联通/移动的 IPTV 直播流是组播(multicast)，走在光猫 ITV 口独立 VLAN 里，与家庭局域网隔离。
关键事实（抓包实测总结）：
  · 组播免鉴权：任何设备进入该 VLAN 并加入组播组即可收流；DHCP+ 鉴权只影响单播业务(EPG/回看/时移)。
  · 傻瓜交换机没有 IGMP Snooping，会把组播泛洪到所有口 → 电脑有线口"搭线"即可抓包。
  · 电脑有线口进 ITV 专网后拿不到 DHCP（显示 169.254.x.x）是正常现象，不影响抓包与加组。
  · 抓包用 Windows 内置 pktmon（Win10 1809+），无需安装 Wireshark/Npcap/任何驱动。
  · 本工具验证频道 = 真实加入组播组收流并解析 MPEG-TS（PAT/PMT/SDT），不依赖 ffmpeg。

【三步流程】
  ① 接线向导：回答硬件问卷 → 按步骤插拔网线（光猫ITV口/机顶盒/电脑 三方接傻瓜交换机）。
  ② 抓包分析：开始抓包 → 机顶盒开机重启或逐个换台(每频道停3~5秒) → 停止并分析 → 加入频道列表。
     已桥接合并网络的用户：跳过抓包，直接在 ③ 选择地区载入参考库。
  ③ 频道验证：选省份+运营商载入参考库（或抓包/导入M3U）→ 选组播网卡 → 验证全部 → 自动命名。
  ④ 生成 M3U：选格式与输出目录 → 保存/更新。udp 版给支持组播的设备；http 版配合 ⑤ 转发或路由器 udpxy。
  ⑤ 转发服务(可选)：组播转 HTTP 单播，WiFi 设备播放更稳；播放列表地址复制到 VLC/Kodi/DIYP。

【路由器 IPTV 口场景（免交换机，推荐新路由用户）】
很多新路由（TP-Link/华为/小米/华硕等）带 IPTV 口/VLAN 绑定/单线复用功能，可代替傻瓜交换机：
  1 光猫 ITV（或单线复用 VLAN）→ 路由 WAN；在路由里把某个 LAN 口绑定为 IPTV 口。
  2 机顶盒接该 IPTV 口；电脑接普通 LAN 口。无需傻瓜交换机、无需改光猫。
  3 若路由有 IGMP Proxy/组播转发/组播增强：开启后组播进入整个 LAN，电脑直接抓包/验证，最方便。
  4 若组播不进 LAN：把电脑也接 IPTV 绑定口（若支持多口），或在该口下接傻瓜交换机分给机顶盒+电脑。
向导里选「路由器带 IPTV 口/VLAN 绑定」即按此生成步骤与拓扑图。

【全国参考库与更新】
  · 内嵌全国 31 省×电信/联通/移动/广电组播参考库（社区开源仓库 xisohi/CHINA-IPTV，每日更新；浙江电信经实测校验）。
  · 在线更新：③ 页「在线更新参考库」→ 自动尝试国内加速镜像/GitHub API/git 克隆，结果存到程序目录 refdb.json。
  · 离线更新：从 QQ 群（170621740）下载最新 refdb.json，放到程序目录即自动生效；也可用「导入参考库文件」。
  · 运营商/地区变化（如换宽带）：重新选择地区载入，或重新抓包；参考库只是候选，一切以本机实测验证为准。
  · 隐私：软件不后台联网、不上传任何数据；抓包看到的机顶盒账号仅显示在你本机屏幕，不写入配置。

【桥接合并（进阶，全家直看组播）】
抓源完成后，把路由器 LAN 也接进傻瓜交换机 → IPTV 专网与家庭 LAN 二层合并 → 全家设备直接播放 udp:// 列表，无需任何服务。
安全性：IPTV 的 DHCP+ 服务器不响应无 option60 的普通设备，不会抢路由器 DHCP（实测）。
注意：合并后重新接回机顶盒可能从路由器拿错 IP 导致认证失败 → 拔掉桥接线即恢复隔离。

【故障排查】
  抓包 0 结果        → 是否管理员运行？机顶盒是否开机换台？交换机是否傻瓜型(关 IGMP Snooping)？网线是否插紧？
  有线口无 169.254   → 网线/交换机口坏，换口；确认接的是 ITV 信号线而不是上网线。
  验证全部失败       → 组播网卡选错？搭线阶段选有线口(169.254.x)；已桥接选有线口(192.168.x)。个别路由器 WiFi 不转发组播。
  个别频道不可用     → 停播/未开通/外地地方台不在本地播发；参考库地址随运营商调整会变化，以实测为准。
  播放卡顿           → 组播过 WiFi 依赖路由器组转单能力；改用 ⑤ HTTP 转发，或播放设备走有线/5G WiFi。
  全部频道打不开     → 桥接线是否松了？交换机是否通电？电脑有线口是否还在 IPTV 网络里？
  HTTP 版地址失效    → 电脑 IP 变了：在路由器里给电脑绑定静态 IP，然后重新生成 M3U。
  在线更新失败       → 网络波动/镜像失效，稍后重试；或 QQ 群下载 refdb.json 离线更新。

【已知限制】
  · 参考库为社区收集，各地运营商随时可能调整组播地址，载入后务必实测验证；SDT 解析可自动命名大部分频道。
  · 不含 EPG 节目单与回看/时移（需克隆机顶盒 DHCP option60 获取单播业务，属进阶玩法）。
  · 转发服务依赖本机开机；7×24 需求请用 NAS(Tvheadend)/路由器(udpxy) 方案。
  · 所有服务仅限局域网，禁止映射公网。

【关于】
无双IPTV抓源工具 · 作者：B站-锤无双 · QQ群 170621740
视频教程：https://www.bilibili.com/video/BV17SWk6VEPZ/
开源仓库：https://github.com/chuiziyao/wushuang-iptv
配置保存在程序目录 WushuangIPTV.json；参考库更新文件 refdb.json；抓包临时目录 cap_temp（默认自动清理）。
技术：pktmon 抓包 / pcap+pcapng 解析(去重) / IGMP 分析 / 原生 TS(PAT/PMT/SDT/SPS) 解析 / 组播加组验证 / udpxy 等价转发。
'''


def _setup_window_icon(root):
    """窗口/任务栏电视图标（exe 文件图标由 PyInstaller --icon 设置）。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    ico = os.path.join(base, 'app.ico')
    if os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass


def main():
    if '--selftest' in sys.argv:
        import selftest
        selftest.main()
        return
    try:
        ctypes = __import__('ctypes')
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        # 任务栏图标与窗口一致（否则 Windows 任务栏显示 python 默认图标）
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Wushuang.IPTV.Tool.2')
    except Exception:
        pass
    root = tk.Tk()
    _setup_window_icon(root)
    app = App(root)
    if '--smoke' in sys.argv:
        def quit_soon():
            app._on_close()
        root.after(1200, quit_soon)
        root.mainloop()
        print('SMOKE OK')
        return
    root.mainloop()


if __name__ == '__main__':
    main()
