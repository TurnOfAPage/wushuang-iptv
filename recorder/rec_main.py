# -*- coding: utf-8 -*-
"""无双IPTV录像工具 · 独立 GUI（Windows / Linux / macOS）
把免鉴权收到的组播直播流录下来，事后局域网点播：即时录 / EPG 预约 / 录像管理 / 常驻服务。
独立产品：复用 src/ 核心模块（record/epg/proxy/verify/channeldb），主工具不受影响。
作者：锤无双  https://www.bilibili.com/video/BV17SWk6VEPZ/
"""
import json
import os
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:  # 无头 NAS：CLI 仍可用
    tk = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import channeldb
import epg
import m3u
import netutil
import proxy
import record
import verify
from recinfo import (REC_NAME, REC_VER_DISPLAY, BETA_NOTE, AUTHOR, AUTHOR_URL,
                     QQ_GROUP, REPO_URL)

# ---- 配色/字体（与主工具同一视觉语言） ----
BG = '#f2f5fa'
CARD = '#ffffff'
ACCENT = '#2563eb'
TEXT = '#1f2937'
SUB = '#64748b'
OKC = '#16a34a'
BADC = '#dc2626'
WARNC = '#d97706'
FONT_FAMILY = ('Microsoft YaHei UI' if netutil.IS_WIN else
               'PingFang SC' if netutil.IS_MAC else 'Noto Sans CJK SC')
MONO_FAMILY = 'Consolas' if netutil.IS_WIN else ('Menlo' if netutil.IS_MAC else 'DejaVu Sans Mono')
SCALE = 1.0


def px(n):
    return int(round(n * SCALE))


def F(size, bold=False):
    return (FONT_FAMILY, size, 'bold') if bold else (FONT_FAMILY, size)


FONT = F(10)
FONT_B = F(10, True)
FONT_S = F(9)
MONO = (MONO_FAMILY, 10)


def _finalize_fonts(root):
    global FONT_FAMILY, MONO_FAMILY, FONT, FONT_B, FONT_S, MONO
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
    except Exception:
        return
    if FONT_FAMILY not in fams:
        for cand in ('Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC',
                     'Source Han Sans SC', 'WenQuanYi Micro Hei', 'Droid Sans Fallback'):
            if cand in fams:
                FONT_FAMILY = cand
                break
    if MONO_FAMILY not in fams:
        for cand in ('Consolas', 'Menlo', 'DejaVu Sans Mono', 'Liberation Mono', 'Courier New'):
            if cand in fams:
                MONO_FAMILY = cand
                break
    FONT, FONT_B, FONT_S, MONO = F(10), F(10, True), F(9), (MONO_FAMILY, 10)


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return HERE


CFG_PATH = os.path.join(app_dir(), 'WushuangRecorder.json')
DEFAULT_CFG = {
    'channels': [], 'iface': '', 'record_dir': '', 'proxy_port': 9999,
    'quota_gb': 100, 'pad_before': 60, 'pad_after': 120, 'max_concurrent': 2,
    'missed': 'skip', 'epg_url': '', 'epg_update_on_start': False,
    'last_province': '', 'last_carrier': '',
}


def fmt_size(n):
    if n >= 1024 ** 3:
        return '%.2f GB' % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return '%.1f MB' % (n / 1024 ** 2)
    return '%d KB' % (n // 1024)


def fmt_dur(s):
    s = int(s or 0)
    return '%02d:%02d:%02d' % (s // 3600, s % 3600 // 60, s % 60)


class FieldDialog(tk.Toplevel):
    """简易字段对话框（同主工具 EditDialog 交互）。"""

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
            self.vars[key] = v
        bf = ttk.Frame(self)
        bf.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(bf, text='确定', style='Accent.TButton', command=self._ok).pack(side='left', padx=6)
        ttk.Button(bf, text='取消', command=self.destroy).pack(side='left', padx=6)
        self.transient(master)
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.destroy()


class RecApp:
    def __init__(self, root):
        self.root = root
        root.title('%s v%s' % (REC_NAME, REC_VER_DISPLAY))
        root.geometry('%dx%d' % (px(1150), px(800)))
        root.minsize(px(1000), px(680))
        root.configure(bg=BG)
        try:
            root.tk.call('tk', 'scaling', 1.25 * SCALE)
        except tk.TclError:
            pass
        self.cfg = self._load_cfg()
        self.channels = self.cfg.get('channels', [])
        if not self.channels:
            self._migrate_channels()
        self._dir_note = ''
        if not record.dir_writable(self._record_dir()):
            fb = os.path.join(app_dir(), 'recordings')
            self.cfg['record_dir'] = fb
            self._dir_note = ('⚠ 默认下载文件夹被安全软件拒绝写入，已改用 %s；'
                              '如需存下载文件夹，请在火绒/Windows 安全中心信任本程序后到设置改回。' % fb)
        _finalize_fonts(root)
        self.ifaces = netutil.list_interfaces()
        self.q = queue.Queue()
        self.rec_mgr = None       # 手动即时录（scheduler=False）
        self.svc_mgr = None       # 常驻服务调度（scheduler=True）
        self.proxy_srv = None
        self.ver_thread = None
        self.ver_stop = threading.Event()
        self._last_rec_refresh = 0
        self._build_style()
        ttk.Label(root, text='⚠ ' + record.COPYRIGHT_NOTE, style='Banner.TLabel',
                  wraplength=px(1100), justify='left').pack(side='bottom', fill='x', padx=8, pady=(0, 6))
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='both', expand=True, padx=8, pady=6)
        self._build_channels()
        self._build_manage()
        self._build_service()
        self._build_help()
        self._refresh_iface_widgets()
        self._reload_channel_tree()
        self._refresh_manage()
        self.root.after(100, self._poll)
        self.root.after(1000, self._tick)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        if self.cfg.get('epg_update_on_start'):
            self._epg_update()  # 用户显式 opt-in 的启动更新

    # ================= 配置 =================
    def _load_cfg(self):
        cfg = dict(DEFAULT_CFG)
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
        except OSError:
            pass

    # ================= 样式 =================
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use('clam')
        except tk.TclError:
            pass
        st.configure('.', background=BG, foreground=TEXT, font=FONT)
        st.configure('TNotebook', background=BG, borderwidth=0)
        st.configure('TNotebook.Tab', background='#e6ebf2', foreground=SUB,
                     padding=[px(14), px(7)], font=FONT_B)
        st.map('TNotebook.Tab', background=[('selected', CARD)], foreground=[('selected', ACCENT)])
        st.configure('TLabelframe', background=CARD, foreground=TEXT)
        st.configure('TLabelframe.Label', background=CARD, foreground=ACCENT, font=FONT_B)
        st.configure('TFrame', background=CARD)
        st.configure('TLabel', background=CARD, foreground=TEXT)
        st.configure('Hint.TLabel', foreground=SUB, font=FONT_S, background=CARD)
        st.configure('Ok.TLabel', foreground=OKC, background=CARD)
        st.configure('Warn.TLabel', foreground=WARNC, background=CARD)
        st.configure('Banner.TLabel', foreground=BADC, background=BG, font=FONT_S)
        st.configure('Bad.TLabel', foreground=BADC, background=CARD)
        st.configure('TButton', padding=[px(8), px(4)])
        st.configure('Accent.TButton', background=ACCENT, foreground='white', font=FONT_B)
        st.map('Accent.TButton', background=[('active', '#1d4ed8')])
        st.configure('Treeview', background=CARD, fieldbackground=CARD,
                     foreground=TEXT, rowheight=px(26), font=FONT_S)
        st.configure('Treeview.Heading', background='#e8edf5', foreground=TEXT, font=FONT_S)
        st.configure('TCheckbutton', background=CARD)
        st.configure('TRadiobutton', background=CARD)

    def _make_tree(self, parent, cols, heads, widths):
        tree = ttk.Treeview(parent, columns=cols, show='headings', selectmode='extended')
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=px(w), anchor='w')
        vs = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y')
        return tree

    # ================= ① 频道与录制 =================
    def _build_channels(self):
        self.tab_ch = ttk.Frame(self.nb)
        self.nb.add(self.tab_ch, text=' ① 频道与录制 ')
        top = ttk.LabelFrame(self.tab_ch, text='频道来源：主工具 verify 结果 JSON / M3U / 参考库（录制不需要管理员）')
        top.pack(fill='x', padx=6, pady=6)
        r = ttk.Frame(top)
        r.pack(fill='x', padx=6, pady=4)
        ttk.Label(r, text='组播网卡:').pack(side='left')
        self.ch_iface_cb = ttk.Combobox(r, width=42, state='readonly')
        self.ch_iface_cb.pack(side='left', padx=4)
        ttk.Button(r, text='刷新网卡', command=self._refresh_iface_widgets).pack(side='left', padx=4)
        r2 = ttk.Frame(top)
        r2.pack(fill='x', padx=6, pady=(0, 4))
        ttk.Button(r2, text='导入频道文件…', style='Accent.TButton',
                   command=self._import_channels).pack(side='left', padx=4)
        ttk.Button(r2, text='📚 载入参考库', command=self._load_ref).pack(side='left', padx=4)
        ttk.Button(r2, text='验证全部', command=lambda: self._verify(False)).pack(side='left', padx=4)
        ttk.Button(r2, text='验证选中', command=lambda: self._verify(True)).pack(side='left', padx=4)
        self.ver_stop_btn = ttk.Button(r2, text='停止验证', command=self.ver_stop.set, state='disabled')
        self.ver_stop_btn.pack(side='left', padx=4)
        ttk.Button(r2, text='手动添加', command=self._add_manual).pack(side='left', padx=4)
        ttk.Button(r2, text='删除选中', command=self._del_selected).pack(side='left', padx=4)
        r3 = ttk.Frame(top)
        r3.pack(fill='x', padx=6, pady=(0, 6))
        self.rec_btn = ttk.Button(r3, text='⏺ 录制选中', style='Accent.TButton',
                                  command=self._record_selected)
        self.rec_btn.pack(side='left', padx=4)
        self.rec_stop_btn = ttk.Button(r3, text='■ 停止全部录制', command=self._stop_all_rec,
                                       state='disabled')
        self.rec_stop_btn.pack(side='left', padx=4)
        self.rec_state_lbl = ttk.Label(r3, text='未在录制', style='Hint.TLabel')
        self.rec_state_lbl.pack(side='left', padx=10)
        self.ver_prog = ttk.Progressbar(top, mode='determinate')
        self.ver_prog.pack(fill='x', padx=6, pady=(0, 4))
        cols = ('name', 'group', 'port', 'cat', 'status', 'video', 'res')
        heads = ('频道名', '组播地址', '端口', '分类', '状态', '视频', '分辨率')
        widths = (170, 135, 55, 95, 95, 70, 90)
        tf = ttk.Frame(self.tab_ch)
        tf.pack(fill='both', expand=True, padx=6, pady=(0, 4))
        self.ch_tree = self._make_tree(tf, cols, heads, widths)
        self.ch_empty_lbl = ttk.Label(self.tab_ch, text='', style='Hint.TLabel',
                                      wraplength=px(1080), justify='left')
        self.ch_empty_lbl.pack(fill='x', padx=8, pady=(0, 4))
        ttk.Label(self.tab_ch, text='提示：频道建议先用主工具实测验证（或在本页「验证全部」）。'
                  '录制=把直播流存盘，只能录开始之后的内容，不能回溯过去。',
                  style='Hint.TLabel', wraplength=px(1080), justify='left').pack(fill='x', padx=8, pady=(0, 6))

    def _iface_labels(self):
        out = []
        for i in self.ifaces:
            tag = {'wired': '有线', 'wifi': 'WiFi'}.get(i['kind'], i['kind'])
            out.append('%s [%s] %s %s' % (i['name'], tag, i['ipv4'],
                                          '(网关 %s)' % i['gateway'] if i['gateway'] else ''))
        return out

    def _refresh_iface_widgets(self):
        self.ifaces = netutil.list_interfaces()
        labels = self._iface_labels()
        for cb in (self.ch_iface_cb, self.svc_iface_cb):
            cb['values'] = labels
        sug = netutil.pick_multicast_iface(self.ifaces)
        saved = self.cfg.get('iface', '')
        for cb in (self.ch_iface_cb, self.svc_iface_cb):
            idx = 0
            for n, i in enumerate(self.ifaces):
                if i['ipv4'] == (saved or sug):
                    idx = n
                    break
            if labels:
                cb.current(idx)

    def _selected_iface_ip(self, cb):
        n = cb.current()
        if 0 <= n < len(self.ifaces):
            return self.ifaces[n]['ipv4']
        return ''

    def _reload_channel_tree(self):
        self.ch_tree.delete(*self.ch_tree.get_children())
        if not self.channels:
            self.ch_empty_lbl.config(
                text='频道列表为空：点「导入频道文件…」选主工具 verify 结果 JSON / M3U，'
                     '或「载入参考库」→「验证全部」；然后选中频道行点「⏺ 录制选中」。')
        else:
            self.ch_empty_lbl.config(text='')
        for ch in m3u.sort_channels(self.channels):
            st = '✓ 可用' if ch.get('ok') else ('未验证' if not ch.get('tested') else '✗ 不可用')
            self.ch_tree.insert('', 'end', values=(
                ch.get('name', ''), ch['group'], ch['port'], ch.get('cat', ''),
                st, ch.get('video') or '', ch.get('res') or ''))

    def _merge_channels(self, new):
        old = {(c['group'], c['port']): c for c in self.channels}
        for c in new:
            k = (c['group'], c['port'])
            if k in old:
                o = old[k]
                if c.get('tested'):
                    o.update({x: c.get(x) for x in ('ok', 'tested', 'video', 'audio', 'res', 'sdt_name')})
                if c.get('name') and not o.get('user_named'):
                    o['name'] = c['name']
            else:
                old[k] = c
        self.channels = list(old.values())
        self._reload_channel_tree()
        self._save_cfg()

    def _import_channels(self):
        p = filedialog.askopenfilename(title='选择频道文件', filetypes=[
            ('频道文件', '*.json *.m3u *.m3u8'), ('所有文件', '*.*')])
        if not p:
            return
        try:
            import rec_cli
            chans = rec_cli.read_channels(p)
            self._merge_channels(chans)
            messagebox.showinfo(REC_NAME, '已导入 %d 个频道。' % len(chans))
        except Exception as e:
            messagebox.showerror(REC_NAME, '导入失败: %s' % e)

    def _load_ref(self):
        provs = channeldb.provinces()
        d = FieldDialog(self.root, '载入参考库（候选，未实测）',
                        [('province', '省份', self.cfg.get('last_province') or provs[0]),
                         ('carrier', '运营商(电信/联通/移动/广电)', self.cfg.get('last_carrier') or '电信')])
        if not d.result:
            return
        prov = channeldb.PROV.get(d.result['province'], d.result['province'])
        carrier = channeldb.CARRIER.get(d.result['carrier'], d.result['carrier'])
        try:
            chans = channeldb.channels_for(prov, carrier)
        except Exception as e:
            messagebox.showerror(REC_NAME, str(e))
            return
        if not chans:
            messagebox.showerror(REC_NAME, '未找到 %s %s 的参考列表' % (prov, carrier))
            return
        self.cfg['last_province'], self.cfg['last_carrier'] = prov, carrier
        self._merge_channels(chans)
        messagebox.showinfo(REC_NAME, '已载入 %d 个候选频道，请「验证全部」实测。' % len(chans))

    def _selected_channels(self):
        sels = self.ch_tree.selection()
        out = []
        for s in sels:
            v = self.ch_tree.item(s, 'values')
            for ch in self.channels:
                if ch['group'] == v[1] and str(ch['port']) == str(v[2]):
                    out.append(ch)
                    break
        return out

    def _verify(self, selected_only):
        if self.ver_thread and self.ver_thread.is_alive():
            return
        chans = self._selected_channels() if selected_only else self.channels
        if not chans:
            messagebox.showinfo(REC_NAME, '没有可验证的频道')
            return
        iface = self._selected_iface_ip(self.ch_iface_cb)
        if not iface:
            messagebox.showerror(REC_NAME, '请选择组播网卡')
            return
        self.cfg['iface'] = iface
        self.ver_stop.clear()
        self.ver_prog['maximum'] = len(chans)
        self.ver_prog['value'] = 0
        self.ver_stop_btn.config(state='normal')

        def work():
            def prog(done, total, ch, r):
                channeldb.apply_verify_result(ch, r)
                self.q.put(('ver_prog', done, total, ch.get('name', ''), r['ok']))
            try:
                verify.verify_batch(chans, iface, concurrency=2, timeout=5,
                                    progress_cb=prog, stop_event=self.ver_stop)
            except Exception as e:
                self.q.put(('error', '验证失败: %s' % e))
            self.q.put(('ver_done',))

        self.ver_thread = threading.Thread(target=work, daemon=True)
        self.ver_thread.start()

    def _add_manual(self):
        d = FieldDialog(self.root, '手动添加频道',
                        [('name', '频道名', ''), ('group', '组播地址', '233.50.201.'),
                         ('port', '端口', '5140')])
        if not d.result or not d.result['group']:
            return
        try:
            port = int(d.result['port'])
        except ValueError:
            messagebox.showerror(REC_NAME, '端口必须是数字')
            return
        ref = channeldb.lookup(d.result['group'], port)
        self._merge_channels([{'name': d.result['name'] or (ref['name'] if ref else '未知频道'),
                               'group': d.result['group'], 'port': port,
                               'cat': (ref.get('cat') if ref else '') or '未分类',
                               'ok': False, 'source': 'manual'}])

    def _del_selected(self):
        sels = self._selected_channels()
        if not sels:
            return
        keys = {(c['group'], c['port']) for c in sels}
        self.channels = [c for c in self.channels if (c['group'], c['port']) not in keys]
        self._reload_channel_tree()
        self._save_cfg()

    # ---- 录制 ----
    def _migrate_channels(self):
        """首启空列表时从旧版录像配置/主工具配置迁移频道（向上三级目录查找）。"""
        b = app_dir()
        ups = [b, os.path.dirname(b), os.path.dirname(os.path.dirname(b)),
               os.path.dirname(os.path.dirname(os.path.dirname(b)))]
        for up in ups:
            for name in ('WushuangRecorder.json', 'WushuangIPTV.json'):
                p = os.path.join(up, name)
                try:
                    with open(p, encoding='utf-8') as f:
                        d = json.load(f)
                except (OSError, ValueError):
                    continue
                chans = d.get('channels') or []
                if chans:
                    self.channels = chans
                    self.cfg['channels'] = chans
                    return

    def _record_dir(self):
        return self.cfg.get('record_dir') or record.default_record_dir()

    def _ensure_rec_mgr(self, iface):
        rd = self._record_dir()
        if self.rec_mgr is not None:
            if self.rec_mgr.iface_ip == iface and self.rec_mgr.record_dir == os.path.abspath(rd):
                return self.rec_mgr
            if self.rec_mgr.status()['active']:
                raise ValueError('已有录制在使用其它网卡/目录，请先停止')
            self.rec_mgr.stop()
        try:
            self.rec_mgr = record.RecordManager(
                rd, iface, channels_cb=lambda: self.channels,
                quota_gb=self.cfg.get('quota_gb', 100),
                max_concurrent=self.cfg.get('max_concurrent', 2),
                progress_cb=lambda ev, **kw: self.q.put(('rec', ev, kw)), scheduler=False)
        except (PermissionError, OSError) as e:
            messagebox.showerror(REC_NAME, str(e))
            return None
        return self.rec_mgr

    def _record_selected(self):
        chans = self._selected_channels()
        if not chans:
            messagebox.showinfo(REC_NAME, '请先在频道列表选择要录制的频道（可多选）')
            return
        iface = self._selected_iface_ip(self.ch_iface_cb)
        if not iface:
            messagebox.showerror(REC_NAME, '请选择组播网卡')
            return
        d = FieldDialog(self.root, '录制选中频道（%d 路）' % len(chans),
                        [('minutes', '录制时长(分钟)', '60'),
                         ('until', '或录到 HH:MM（留空=按时长）', ''),
                         ('record_dir', '录像目录', self._record_dir())])
        if not d.result:
            return
        self.cfg['record_dir'] = d.result['record_dir'] or self._record_dir()
        self.cfg['iface'] = iface
        if d.result['until']:
            try:
                t = datetime.strptime(d.result['until'], '%H:%M')
            except ValueError:
                messagebox.showerror(REC_NAME, 'HH:MM 格式不正确')
                return
            now = datetime.now()
            end = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if end <= now:
                end += timedelta(days=1)
            seconds = int((end - now).total_seconds())
        else:
            try:
                seconds = int(float(d.result['minutes']) * 60)
            except ValueError:
                messagebox.showerror(REC_NAME, '时长必须是数字')
                return
        if seconds <= 0:
            messagebox.showerror(REC_NAME, '录制时长必须大于 0')
            return
        try:
            mgr = self._ensure_rec_mgr(iface)
        except ValueError as e:
            messagebox.showerror(REC_NAME, str(e))
            return
        if mgr is None:
            return
        errs, okn = [], 0
        for ch in chans:
            try:
                mgr.record_now(ch, seconds=seconds)
                okn += 1
            except ValueError as e:
                errs.append('%s: %s' % (ch.get('name', ''), e))
        self._save_cfg()
        self.rec_stop_btn.config(state='normal')
        if errs:
            messagebox.showwarning(REC_NAME, '已启动 %d 路；部分失败:\n%s' % (okn, '\n'.join(errs)))
        self._refresh_manage()

    def _stop_all_rec(self):
        if self.rec_mgr:
            self.rec_mgr.stop()
        if self.svc_mgr:
            for s in self.svc_mgr.list_schedules():
                if s['status'] == 'recording':
                    try:
                        self.svc_mgr.cancel(s['id'])
                    except ValueError:
                        pass
        self.rec_stop_btn.config(state='disabled')
        self._refresh_manage()

    # ================= ② 录像管理 =================
    def _build_manage(self):
        self.tab_mg = ttk.Frame(self.nb)
        self.nb.add(self.tab_mg, text=' ② 录像管理 ')
        gf = ttk.LabelFrame(self.tab_mg, text='状态与设置（容量上限 / 保存文件夹）')
        gf.pack(fill='x', padx=6, pady=6)
        gr = ttk.Frame(gf)
        gr.pack(fill='x', padx=6, pady=4)
        ttk.Label(gr, text='容量上限(GB):').pack(side='left')
        self.set_quota_var = tk.IntVar(value=self.cfg.get('quota_gb', 100))
        ttk.Spinbox(gr, from_=0, to=100000, textvariable=self.set_quota_var, width=7).pack(side='left', padx=4)
        ttk.Label(gr, text='保存文件夹:').pack(side='left', padx=(12, 2))
        self.set_rd_var = tk.StringVar(value=self._record_dir())
        ttk.Entry(gr, textvariable=self.set_rd_var, width=40).pack(side='left', padx=4)
        ttk.Button(gr, text='浏览…', command=self._browse_set_rd).pack(side='left', padx=4)
        ttk.Button(gr, text='应用设置', style='Accent.TButton',
                   command=self._apply_settings).pack(side='left', padx=8)
        ttk.Label(gf, text='每小时每频道约 1~4 GB（高清经验值）；标清 1~2、4K 15~22 GB/小时。'
                  '超出上限自动清理最旧已完成录像（不删在录/待录）。',
                  style='Hint.TLabel', wraplength=px(1050), justify='left').pack(fill='x', padx=6, pady=(0, 4))
        if self._dir_note:
            ttk.Label(gf, text=self._dir_note, style='Warn.TLabel',
                      wraplength=px(1050), justify='left').pack(fill='x', padx=6, pady=(0, 4))
        ef = ttk.LabelFrame(self.tab_mg, text='节目单（EPG，公共 XMLTV；仅按钮主动联网更新）')
        ef.pack(fill='x', padx=6, pady=6)
        er = ttk.Frame(ef)
        er.pack(fill='x', padx=6, pady=4)
        ttk.Label(er, text='XMLTV 地址:').pack(side='left')
        self.epg_url_var = tk.StringVar(value=self.cfg.get('epg_url', ''))
        ttk.Entry(er, textvariable=self.epg_url_var, width=48).pack(side='left', padx=4)
        ttk.Button(er, text='🔄 更新节目单', style='Accent.TButton',
                   command=self._epg_update).pack(side='left', padx=6)
        self.epg_auto_var = tk.BooleanVar(value=self.cfg.get('epg_update_on_start', False))
        ttk.Checkbutton(er, text='启动时自动更新(联网)', variable=self.epg_auto_var,
                        command=self._epg_auto_changed).pack(side='left', padx=6)
        self.epg_lbl = ttk.Label(ef, text='尚未更新节目单（预约可手动指定时间段，不依赖 EPG）',
                                 style='Hint.TLabel')
        self.epg_lbl.pack(fill='x', padx=6, pady=(0, 4))
        rf = ttk.LabelFrame(self.tab_mg, text='录像文件（播放链接可在 VLC/Kodi/TiviMate/KmPlayer 打开拖动；点播需 ③ 服务页启动常驻服务）')
        rf.pack(fill='both', expand=True, padx=6, pady=6)
        rr = ttk.Frame(rf)
        rr.pack(fill='x', padx=6, pady=4)
        ttk.Button(rr, text='刷新', command=self._refresh_manage).pack(side='left', padx=4)
        ttk.Button(rr, text='停止选中录制', command=self._stop_selected_rec).pack(side='left', padx=4)
        ttk.Button(rr, text='删除选中录像', command=self._delete_recording).pack(side='left', padx=4)
        ttk.Button(rr, text='打开录像目录', command=self._open_rec_dir).pack(side='left', padx=4)
        ttk.Button(rr, text='复制点播地址', command=self._copy_vod_url).pack(side='left', padx=4)
        self.quota_lbl = ttk.Label(rr, text='', style='Hint.TLabel')
        self.quota_lbl.pack(side='right', padx=6)
        ttk.Button(rr, text='立即清理', command=self._cleanup_quota).pack(side='right', padx=4)
        cols = ('name', 'title', 'start', 'dur', 'size', 'status', 'gaps', 'id')
        heads = ('频道', '节目', '开始时间', '时长', '大小', '状态', '断流', '录像ID')
        widths = (110, 220, 130, 75, 80, 75, 50, 200)
        tf = ttk.Frame(rf)
        tf.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        self.rec_tree = self._make_tree(tf, cols, heads, widths)
        sf = ttk.LabelFrame(self.tab_mg, text='预约计划（到点自动录制，需常驻服务在运行）')
        sf.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        sr = ttk.Frame(sf)
        sr.pack(fill='x', padx=6, pady=4)
        ttk.Button(sr, text='＋ 新增预约…', style='Accent.TButton',
                   command=self._add_schedule).pack(side='left', padx=4)
        ttk.Button(sr, text='取消选中', command=self._cancel_schedule).pack(side='left', padx=4)
        ttk.Button(sr, text='清理历史', command=self._prune_schedules).pack(side='left', padx=4)
        ttk.Button(sr, text='刷新', command=self._refresh_manage).pack(side='left', padx=4)
        cols2 = ('ch', 'title', 'start', 'end', 'status', 'id')
        heads2 = ('频道', '节目', '开始', '结束', '状态', '计划ID')
        widths2 = (130, 260, 140, 140, 80, 90)
        tf2 = ttk.Frame(sf)
        tf2.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        self.sch_tree = self._make_tree(tf2, cols2, heads2, widths2)

    def _plan_mgr(self):
        """写计划用的管理器：优先常驻服务的，否则临时实例（只写文件，不收流）。"""
        if self.svc_mgr is not None:
            return self.svc_mgr
        return record.RecordManager(self._record_dir(), '127.0.0.1', scheduler=False)

    def _refresh_manage(self):
        try:
            mgr = self.svc_mgr or self.rec_mgr
            if mgr is None:
                mgr = record.RecordManager(self._record_dir(), '127.0.0.1', scheduler=False)
            recs = mgr.list_recordings()
            schs = mgr.list_schedules()
            st = mgr.status()
        except Exception:
            return
        self.rec_tree.delete(*self.rec_tree.get_children())
        stmap = {'recording': '⏺ 录制中', 'done': '✓ 完成', 'partial': '◐ 部分',
                 'error': '✗ 错误'}
        for r in sorted(recs, key=lambda x: x.get('start', ''), reverse=True):
            self.rec_tree.insert('', 'end', values=(
                r.get('name', ''), r.get('epg_title', ''),
                (r.get('start', '') or '').replace('T', ' '),
                fmt_dur(r.get('duration')), fmt_size(r.get('bytes', 0)),
                stmap.get(r.get('status', ''), r.get('status', '')),
                r.get('gaps', 0), r.get('id', '')))
        self.sch_tree.delete(*self.sch_tree.get_children())
        smap = {'pending': '待录', 'recording': '⏺ 录制中', 'done': '✓ 完成',
                'missed': '错过', 'canceled': '已取消', 'error': '✗ 错误'}
        for s in sorted(schs, key=lambda x: x.get('start', '')):
            self.sch_tree.insert('', 'end', values=(
                s['channel'].get('name', ''), s.get('epg_title', ''),
                s.get('start', '').replace('T', ' '), s.get('end', '').replace('T', ' '),
                smap.get(s.get('status', ''), s.get('status', '')), s.get('id', '')))
        self.quota_lbl.config(text='配额: %.2f / %s GB · 录像 %d 个 · 待录 %d' % (
            st['quota_used_gb'], st['quota_gb'] or '∞', st['recordings'], st['pending']))
        d = epg.load(self._record_dir())
        if d:
            self.epg_lbl.config(text='节目单: %s 更新 · 源 %s · 映射 %d 频道' % (
                d.get('updated', ''), d.get('source', ''), len(d.get('channels', {}))))

    def _browse_set_rd(self):
        d = filedialog.askdirectory(title='选择录像保存文件夹')
        if d:
            self.set_rd_var.set(d)

    def _apply_settings(self):
        q = self.set_quota_var.get()
        rd = self.set_rd_var.get().strip() or self._record_dir()
        for mgr in (self.rec_mgr, self.svc_mgr):
            if mgr is not None and mgr.status()['active']:
                messagebox.showerror(REC_NAME, '有录制进行中，请先停止再改保存文件夹')
                return
        self.cfg['quota_gb'] = q
        self.cfg['record_dir'] = rd
        self._save_cfg()
        if self.rec_mgr is not None:
            if os.path.abspath(rd) != self.rec_mgr.record_dir:
                self.rec_mgr.stop()
                self.rec_mgr = None
            else:
                self.rec_mgr.save_settings(quota_gb=q)
        if self.svc_mgr is not None:
            if os.path.abspath(rd) != self.svc_mgr.record_dir:
                try:
                    new = record.RecordManager(
                        rd, self.svc_mgr.iface_ip, channels_cb=lambda: self.channels,
                        quota_gb=q, pad_before=self.svc_mgr.pad_before,
                        pad_after=self.svc_mgr.pad_after,
                        max_concurrent=self.svc_mgr.max_concurrent,
                        missed_policy=self.svc_mgr.missed_policy,
                        progress_cb=lambda ev, **kw: self.q.put(('rec', ev, kw)),
                        scheduler=True)
                except (PermissionError, OSError) as e:
                    messagebox.showerror(REC_NAME, str(e))
                    return
                new.start()
                old = self.svc_mgr
                old.stop()
                self.svc_mgr = new
                if self.proxy_srv:
                    self.proxy_srv.record_mgr = new
            else:
                self.svc_mgr.save_settings(quota_gb=q)
        self.svc_rd_var.set(rd)
        self._refresh_manage()
        messagebox.showinfo(REC_NAME, '设置已应用：上限 %s GB\n文件夹 %s' % (q or '不限', rd))

    def _epg_auto_changed(self):
        self.cfg['epg_update_on_start'] = bool(self.epg_auto_var.get())
        self._save_cfg()

    def _epg_update(self):
        url = self.epg_url_var.get().strip()
        self.cfg['epg_url'] = url
        self._save_cfg()
        self.epg_lbl.config(text='正在更新节目单…（主动联网）')

        def work():
            try:
                r = epg.update(self._record_dir(), self.channels, url=url or None,
                               progress_cb=lambda ev, **kw: self.q.put(('epg_prog', ev, kw)))
                self.q.put(('epg_done', r))
            except Exception as e:
                self.q.put(('epg_fail', str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _selected_rec_ids(self):
        return [self.rec_tree.item(s, 'values')[7] for s in self.rec_tree.selection()]

    def _stop_selected_rec(self):
        ids = self._selected_rec_ids()
        mgr = self.svc_mgr or self.rec_mgr
        if not mgr or not ids:
            return
        for s in mgr.list_schedules():
            if s['status'] == 'recording' and s.get('rid') in ids:
                try:
                    mgr.cancel(s['id'])
                except ValueError:
                    pass
        self._refresh_manage()

    def _delete_recording(self):
        ids = self._selected_rec_ids()
        if not ids:
            return
        if not messagebox.askyesno(REC_NAME, '删除选中的 %d 个录像文件？不可恢复。' % len(ids)):
            return
        mgr = self.svc_mgr or self.rec_mgr or self._plan_mgr()
        errs = []
        for rid in ids:
            try:
                mgr.delete_recording(rid)
            except ValueError as e:
                errs.append(str(e))
        if errs:
            messagebox.showwarning(REC_NAME, '\n'.join(errs))
        self._refresh_manage()

    def _open_rec_dir(self):
        rd = self._record_dir()
        os.makedirs(rd, exist_ok=True)
        if netutil.IS_WIN:
            os.startfile(rd)  # noqa
        elif netutil.IS_MAC:
            import subprocess
            subprocess.Popen(['open', rd])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', rd])

    def _copy_vod_url(self):
        ids = self._selected_rec_ids()
        if not ids:
            return
        port = self.cfg.get('proxy_port', 9999)
        lan = netutil.lan_ip_for_udpxy(self.ifaces)
        urls = '\n'.join('http://%s:%d/vod/%s' % (lan, port, rid) for rid in ids)
        self.root.clipboard_clear()
        self.root.clipboard_append(urls)
        messagebox.showinfo(REC_NAME, '已复制点播地址（需 ③ 服务页常驻服务在运行）:\n%s' % urls)

    def _cleanup_quota(self):
        mgr = self.svc_mgr or self.rec_mgr or self._plan_mgr()
        mgr.cleanup_quota()
        self._refresh_manage()

    def _cancel_schedule(self):
        ids = [self.sch_tree.item(s, 'values')[5] for s in self.sch_tree.selection()]
        if not ids:
            return
        mgr = self.svc_mgr or self._plan_mgr()
        errs = []
        for sid in ids:
            try:
                mgr.cancel(sid)
            except ValueError as e:
                errs.append(str(e))
        if errs:
            messagebox.showwarning(REC_NAME, '\n'.join(errs))
        self._refresh_manage()

    def _prune_schedules(self):
        mgr = self.svc_mgr or self._plan_mgr()
        mgr.prune_schedules()
        self._refresh_manage()

    def _add_schedule(self):
        if not self.channels:
            messagebox.showinfo(REC_NAME, '请先在 ① 页导入/载入频道')
            return
        dlg = tk.Toplevel(self.root)
        dlg.title('新增预约')
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        frm = ttk.Frame(dlg)
        frm.pack(fill='both', expand=True, padx=10, pady=10)
        ttk.Label(frm, text='频道:').grid(row=0, column=0, sticky='e', pady=4)
        names = [c.get('name', '') for c in m3u.sort_channels(self.channels)]
        ch_cb = ttk.Combobox(frm, values=names, width=32, state='readonly')
        ch_cb.grid(row=0, column=1, columnspan=2, sticky='w', pady=4)
        if names:
            ch_cb.current(0)
        mode = tk.StringVar(value='manual')
        ttk.Radiobutton(frm, text='手动时间段', variable=mode, value='manual').grid(
            row=1, column=0, sticky='w', pady=4)
        ttk.Radiobutton(frm, text='EPG 节目单点选', variable=mode, value='epg').grid(
            row=1, column=1, sticky='w', pady=4)
        mf = ttk.LabelFrame(frm, text='手动时间段')
        mf.grid(row=2, column=0, columnspan=3, sticky='we', pady=4)
        today = datetime.now().strftime('%Y-%m-%d')
        ttk.Label(mf, text='日期:').grid(row=0, column=0, padx=6, pady=4, sticky='e')
        date_var = tk.StringVar(value=today)
        ttk.Entry(mf, textvariable=date_var, width=12).grid(row=0, column=1, padx=4)
        ttk.Label(mf, text='开始 HH:MM:').grid(row=0, column=2, padx=6, sticky='e')
        t1_var = tk.StringVar(value='19:30')
        ttk.Entry(mf, textvariable=t1_var, width=7).grid(row=0, column=3, padx=4)
        ttk.Label(mf, text='结束 HH:MM:').grid(row=0, column=4, padx=6, sticky='e')
        t2_var = tk.StringVar(value='21:30')
        ttk.Entry(mf, textvariable=t2_var, width=7).grid(row=0, column=5, padx=4)
        ef = ttk.LabelFrame(frm, text='EPG 节目（双击选择；需先更新节目单）')
        ef.grid(row=3, column=0, columnspan=3, sticky='we', pady=4)
        plist = tk.Listbox(ef, width=64, height=8, font=FONT_S)
        plist.pack(fill='both', expand=True, padx=6, pady=6)
        progs = []

        def load_progs(*_):
            nonlocal progs
            plist.delete(0, 'end')
            name = ch_cb.get()
            progs = epg.programs(self._record_dir(), name)
            for p in progs:
                plist.insert('end', '%s ~ %s  %s' % (
                    p['start'][5:16].replace('T', ' '), p['stop'][11:16], p['title']))
            if not progs:
                plist.insert('end', '（无节目单：请先在上方更新节目单，或改用手动时间段）')

        ch_cb.bind('<<ComboboxSelected>>', load_progs)
        load_progs()
        bf = ttk.Frame(frm)
        bf.grid(row=4, column=0, columnspan=3, pady=8)

        def ok():
            name = ch_cb.get()
            ch = next((c for c in self.channels if c.get('name') == name), None)
            if ch is None:
                return
            title, source = '', 'manual'
            try:
                if mode.get() == 'epg':
                    sel = plist.curselection()
                    if not sel or sel[0] >= len(progs):
                        messagebox.showerror(REC_NAME, '请选择一个节目', parent=dlg)
                        return
                    p = progs[sel[0]]
                    start = datetime.fromisoformat(p['start'])
                    end = datetime.fromisoformat(p['stop'])
                    title, source = p['title'], 'epg'
                else:
                    d = date_var.get().strip()
                    start = datetime.strptime('%s %s' % (d, t1_var.get().strip()), '%Y-%m-%d %H:%M')
                    end = datetime.strptime('%s %s' % (d, t2_var.get().strip()), '%Y-%m-%d %H:%M')
                    if end <= start:
                        end += timedelta(days=1)  # 跨午夜
                mgr = self._plan_mgr()
                mgr.add_schedule(ch, start, end, source=source, epg_title=title)
            except ValueError as e:
                messagebox.showerror(REC_NAME, str(e), parent=dlg)
                return
            dlg.destroy()
            self._refresh_manage()
            if self.svc_mgr is None:
                messagebox.showinfo(REC_NAME, '计划已保存。启动 ③ 页常驻服务后到点自动录制。')

        ttk.Button(bf, text='确定预约', style='Accent.TButton', command=ok).pack(side='left', padx=6)
        ttk.Button(bf, text='取消', command=dlg.destroy).pack(side='left', padx=6)
        plist.bind('<Double-1>', lambda e: ok())
        dlg.wait_window(dlg)

    # ================= ③ 服务 =================
    def _build_service(self):
        self.tab_sv = ttk.Frame(self.nb)
        self.nb.add(self.tab_sv, text=' ③ 常驻服务 ')
        top = ttk.LabelFrame(self.tab_sv, text='直播转发 + 预约录像调度 + 录像点播（一个服务全搞定；NAS 请用 CLI proxy）')
        top.pack(fill='x', padx=6, pady=6)
        r = ttk.Frame(top)
        r.pack(fill='x', padx=6, pady=4)
        ttk.Label(r, text='监听端口:').pack(side='left')
        self.svc_port_var = tk.IntVar(value=self.cfg.get('proxy_port', 9999))
        ttk.Spinbox(r, from_=1, to=65535, textvariable=self.svc_port_var, width=7).pack(side='left', padx=4)
        ttk.Label(r, text='组播网卡:').pack(side='left', padx=(12, 2))
        self.svc_iface_cb = ttk.Combobox(r, width=42, state='readonly')
        self.svc_iface_cb.pack(side='left', padx=4)
        r2 = ttk.Frame(top)
        r2.pack(fill='x', padx=6, pady=4)
        ttk.Label(r2, text='录像目录:').pack(side='left')
        self.svc_rd_var = tk.StringVar(value=self._record_dir())
        ttk.Entry(r2, textvariable=self.svc_rd_var, width=44).pack(side='left', padx=4)
        ttk.Button(r2, text='浏览…', command=self._browse_rd).pack(side='left', padx=4)
        ttk.Label(r2, text='配额GB:').pack(side='left', padx=(12, 2))
        self.svc_quota_var = tk.IntVar(value=self.cfg.get('quota_gb', 20))
        ttk.Spinbox(r2, from_=0, to=10000, textvariable=self.svc_quota_var, width=6).pack(side='left')
        ttk.Label(r2, text='并发:').pack(side='left', padx=(12, 2))
        self.svc_conc_var = tk.IntVar(value=self.cfg.get('max_concurrent', 2))
        ttk.Spinbox(r2, from_=1, to=8, textvariable=self.svc_conc_var, width=4).pack(side='left')
        r3 = ttk.Frame(top)
        r3.pack(fill='x', padx=6, pady=4)
        self.svc_start_btn = ttk.Button(r3, text='▶ 启动服务', style='Accent.TButton',
                                        command=self._svc_start)
        self.svc_start_btn.pack(side='left', padx=4)
        self.svc_stop_btn = ttk.Button(r3, text='■ 停止', command=self._svc_stop, state='disabled')
        self.svc_stop_btn.pack(side='left', padx=4)
        self.svc_state_lbl = ttk.Label(top, text='未运行。启动后首次会弹防火墙提示，请点「允许(专用网络)」。',
                                       style='Hint.TLabel', wraplength=px(1050), justify='left')
        self.svc_state_lbl.pack(fill='x', padx=6, pady=(0, 6))
        uf = ttk.LabelFrame(self.tab_sv, text='播放地址（复制到 VLC / Kodi / TiviMate）')
        uf.pack(fill='x', padx=6, pady=6)
        self.svc_url_lbl = ttk.Label(uf, text='', font=MONO, wraplength=px(1050), justify='left')
        self.svc_url_lbl.pack(fill='x', padx=8, pady=6)
        sf = ttk.LabelFrame(self.tab_sv, text='服务状态（每 2 秒刷新）')
        sf.pack(fill='both', expand=True, padx=6, pady=6)
        self.svc_status_txt = tk.Text(sf, height=8, font=MONO, bg='#fbfcfe', fg=TEXT,
                                      state='disabled', relief='solid', bd=1, highlightthickness=0)
        self.svc_status_txt.pack(fill='both', expand=True, padx=4, pady=4)
        ttk.Label(self.tab_sv, text='⚠ 仅限局域网使用，禁止把端口映射到公网。预约录像需本服务保持运行；'
                  '7×24 场景推荐 NAS 部署 CLI：proxy --channels verified.json --record-dir /volume1/iptv/rec',
                  style='Warn.TLabel', wraplength=px(1050), justify='left').pack(fill='x', padx=8, pady=(0, 8))

    def _browse_rd(self):
        d = filedialog.askdirectory(title='选择录像目录')
        if d:
            self.svc_rd_var.set(d)

    def _svc_start(self):
        if self.proxy_srv and self.proxy_srv.running:
            return
        iface = self._selected_iface_ip(self.svc_iface_cb)
        if not iface:
            messagebox.showerror(REC_NAME, '请选择组播网卡')
            return
        rd = self.svc_rd_var.get().strip() or self._record_dir()
        port = self.svc_port_var.get()
        self.cfg.update({'proxy_port': port, 'record_dir': rd, 'iface': iface,
                         'quota_gb': self.svc_quota_var.get(),
                         'max_concurrent': self.svc_conc_var.get()})
        self._save_cfg()
        try:
            self.svc_mgr = record.RecordManager(
                rd, iface, channels_cb=lambda: self.channels,
                quota_gb=self.svc_quota_var.get(),
                pad_before=self.cfg.get('pad_before', 60),
                pad_after=self.cfg.get('pad_after', 120),
                max_concurrent=self.svc_conc_var.get(),
                missed_policy=self.cfg.get('missed', 'skip'),
                progress_cb=lambda ev, **kw: self.q.put(('rec', ev, kw)), scheduler=True)
            self.svc_mgr.start()
            self.proxy_srv = proxy.ProxyServer(iface, port, lambda: self.channels,
                                               record_mgr=self.svc_mgr)
            ok, msg = self.proxy_srv.start()
        except Exception as e:
            messagebox.showerror(REC_NAME, '启动失败: %s' % e)
            return
        if not ok:
            self.svc_mgr.stop()
            self.svc_mgr = None
            messagebox.showerror(REC_NAME, msg)
            return
        self.svc_start_btn.config(state='disabled')
        self.svc_stop_btn.config(state='normal')
        self.svc_state_lbl.config(text='运行中: %s' % msg, style='Ok.TLabel')
        lan = netutil.lan_ip_for_udpxy(self.ifaces)
        self.svc_url_lbl.config(text=(
            '直播列表: http://%s:%d/playlist.m3u\n'
            '录像列表: http://%s:%d/recordings.m3u\n'
            '状态页:   http://%s:%d/status' % (lan, port, lan, port, lan, port)))
        self._refresh_manage()

    def _svc_stop(self):
        if self.proxy_srv:
            self.proxy_srv.stop()
        if self.svc_mgr:
            self.svc_mgr.stop()
            self.svc_mgr = None
        self.svc_start_btn.config(state='normal')
        self.svc_stop_btn.config(state='disabled')
        self.svc_state_lbl.config(text='已停止。', style='Hint.TLabel')
        self._refresh_manage()

    # ================= ④ 帮助 =================
    def _build_help(self):
        self.tab_hp = ttk.Frame(self.nb)
        self.nb.add(self.tab_hp, text=' ④ 帮助/关于 ')
        txt = tk.Text(self.tab_hp, font=FONT_S, bg=CARD, fg=TEXT, relief='flat',
                      wrap='word', padx=12, pady=10)
        txt.pack(fill='both', expand=True, padx=6, pady=6)
        txt.insert('end', HELP_TEXT)
        txt.config(state='disabled')

    # ================= 事件循环 =================
    def _poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == 'ver_prog':
                    _, done, total, name, ok = ev
                    self.ver_prog['value'] = done
                    self.ver_prog['maximum'] = total
                elif kind == 'ver_done':
                    self.ver_stop_btn.config(state='disabled')
                    self._reload_channel_tree()
                    self._save_cfg()
                elif kind == 'rec':
                    self._last_rec_refresh = 0  # 下个 tick 刷新管理页
                    if ev[1] == 'record_start':
                        self.rec_stop_btn.config(state='normal')
                    elif ev[1] == 'record_error':
                        self.rec_state_lbl.config(
                            text='✗ 录制错误: %s' % ev[2].get('error', ''), style='Bad.TLabel')
                        messagebox.showerror(REC_NAME, '录制错误: %s' % ev[2].get('error', ''))
                    elif ev[1] == 'record_done':
                        busy = ((self.rec_mgr and self.rec_mgr.status()['active']) or
                                (self.svc_mgr and self.svc_mgr.status()['active']))
                        if not busy:
                            self.rec_stop_btn.config(state='disabled')
                elif kind == 'epg_done':
                    r = ev[1]
                    self.epg_lbl.config(text='节目单更新完成: 映射 %d 频道 / %d 节目（%s）' % (
                        r['mapped'], r['programmes'], r['source']))
                    self._refresh_manage()
                elif kind == 'epg_fail':
                    self.epg_lbl.config(text='节目单更新失败: %s' % ev[1])
                elif kind == 'error':
                    messagebox.showerror(REC_NAME, ev[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _tick(self):
        try:
            if self.rec_mgr is not None:
                self.rec_mgr.poll()
                st = self.rec_mgr.status()
                if st['active']:
                    a = st['active'][0]
                    self.rec_state_lbl.config(text='⏺ %s 已录 %s / %s（共 %d 路）' % (
                        a['name'], fmt_dur(a['duration']), fmt_size(a['bytes']),
                        len(st['active'])), style='Ok.TLabel')
                else:
                    self.rec_state_lbl.config(text='未在录制', style='Hint.TLabel')
            now = time.time()
            if now - self._last_rec_refresh >= 2:
                self._last_rec_refresh = now
                if self.nb.index(self.nb.select()) == 1:
                    self._refresh_manage()
            if self.proxy_srv and self.proxy_srv.running:
                self._update_svc_status()
        except Exception:
            pass
        self.root.after(1000, self._tick)

    def _update_svc_status(self):
        try:
            with self.proxy_srv.lock:
                act = dict(self.proxy_srv.active)
            lines = ['活跃直播流: %s' % (', '.join('%s×%d' % (k, v) for k, v in act.items()) or '无')]
            if self.svc_mgr:
                st = self.svc_mgr.status()
                for a in st['active']:
                    lines.append('⏺ 录制中: %s  %s / %s  断流%d次' % (
                        a['name'], fmt_dur(a['duration']), fmt_size(a['bytes']), a['gaps']))
                lines.append('待录计划: %d（24h内 %d）· 配额 %.2f/%s GB' % (
                    st['pending'], st['pending_24h'], st['quota_used_gb'], st['quota_gb'] or '∞'))
            self.svc_status_txt.config(state='normal')
            self.svc_status_txt.delete('1.0', 'end')
            self.svc_status_txt.insert('end', '\n'.join(lines))
            self.svc_status_txt.config(state='disabled')
        except Exception:
            pass

    def _on_close(self):
        try:
            if self.rec_mgr:
                self.rec_mgr.stop()
            if self.proxy_srv:
                self.proxy_srv.stop()
            if self.svc_mgr:
                self.svc_mgr.stop()
            self.ver_stop.set()
            self.cfg['epg_url'] = self.epg_url_var.get().strip()
            self.cfg['epg_update_on_start'] = bool(self.epg_auto_var.get())
            self._save_cfg()
        except Exception:
            pass
        self.root.destroy()


HELP_TEXT = '''【版权与免责声明（重要）】
⚠ 本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。传播录制文件会导致版权风险，该风险与本软件无关。
录制内容版权归播出方所有；本工具不上传、不分发任何录制文件。

【原理】
IPTV 直播是组播流，进入 ITV 专网加组即可免鉴权接收（主工具「无双IPTV抓源工具」已验证）。
本工具把收到的流存成 TS 文件，事后在局域网点播——这就是「本地录像」。
重要：只能录制开始之后的内容，不能回溯过去（运营商真回看需要机顶盒鉴权，本工具不做）。
常开设备 + 预约录像 = 错过直播随时补看。

【三步用法】
① 频道与录制：导入主工具 verify 结果 JSON / M3U（或载入参考库后「验证全部」）→
   选组播网卡 → 选中频道 → ⏺ 录制选中 → 设定时长。录完文件在录像目录 ts/ 下，VLC 直接可播。
② 录像管理：更新节目单(EPG) → 新增预约（按节目点选或手动时间段）→ 到点自动录。
   预约需要 ③ 页常驻服务保持运行（NAS 场景用 CLI proxy 命令）。
③ 常驻服务：启动后一个服务搞定 直播转发 + 预约调度 + 录像点播。
   播放列表: http://<本机IP>:9999/playlist.m3u   录像列表: http://<本机IP>:9999/recordings.m3u
   推荐播放器: VLC / Kodi / PotPlayer / TiviMate / KmPlayer（录像拖动支持良好）。

【NAS / 软路由 7×24 部署（推荐）】
WushuangIPTV-Recorder-CLI proxy --channels verified.json --record-dir /volume1/iptv/rec
预约:  WushuangIPTV-Recorder-CLI record add --name CCTV5 --start 2026-11-23T19:30 --end 21:30
       WushuangIPTV-Recorder-CLI record add --name CCTV5 --title "英超"（配合 epg update）
节目单: WushuangIPTV-Recorder-CLI epg update --channels verified.json
群晖注意: 需开机任务 sysctl force_igmp_version=2（见主仓库 docker/README.md）；Docker 用 host 网络。

【可靠性】
· 断流自动重加组续录（IGMP 60s 续期，防光猫侧老化）；重启后计划自动恢复/续录。
· 磁盘预检 + 配额 LRU 自动清理（绝不删进行中/待录文件）；单文件超 4GiB/2h 自动分段。
· 并发默认 2 路（光猫可能限速加组）；录像不需要管理员/root。

【已知限制】
· 不能回溯过去；预约时刻设备必须开机且服务在运行。
· 每小时每频道约 1~3.6 GB（4K 更高），请合理设置配额。
· 公共 EPG 源时效/准确度有限，预约已留提前/延后余量；也可手动指定时间段。
· 仅限局域网，禁止映射公网；录像仅供个人观看。

【关于】
%s v%s · 作者：%s · QQ群 %s
独立产品，与主工具「无双IPTV抓源工具」共享核心模块；不需要录像的用户无需安装本工具。
%s
''' % (REC_NAME, REC_VER_DISPLAY, AUTHOR, QQ_GROUP, BETA_NOTE)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'cli':
        import rec_cli
        sys.exit(rec_cli.main(sys.argv[2:]))
    if '--selftest' in sys.argv:
        import selftest_rec
        selftest_rec.main()
        return
    if tk is None:
        if sys.stderr is not None:
            print('未安装 tkinter，无法启动图形界面。命令行功能不受影响：\n'
                  '  python3 rec_main.py cli <子命令>', file=sys.stderr)
        sys.exit(1)
    global SCALE
    if netutil.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Wushuang.IPTV.Recorder.1')
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi > 0:
                SCALE = dpi / 96.0
        except Exception:
            pass
    root = tk.Tk()
    ico = os.path.join(os.path.dirname(HERE), 'src', 'app.ico')
    if getattr(sys, 'frozen', False):
        ico = os.path.join(sys._MEIPASS, 'app.ico')
    if netutil.IS_WIN and os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass
    app = RecApp(root)
    if '--smoke' in sys.argv:
        root.after(1200, app._on_close)
        root.mainloop()
        if sys.stdout is not None:
            print('SMOKE OK')
        return
    root.mainloop()


if __name__ == '__main__':
    main()
