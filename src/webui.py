# -*- coding: utf-8 -*-
"""内置 Web 管理页（NAS Docker / 常驻服务场景）：纯标准库、内嵌 HTML/JS、零外部资源。
仅当 ProxyServer(record_mgr=...) 启用；主工具（不传 record_mgr）行为完全不变。
页面: / （或 /admin /ui）；区块顺序：状态与设置 → 预约录像 → 录像 → 频道与录制。
API: GET /api/state、/api/programs?name=；POST /api/record/start|stop、
/api/schedule/add|cancel、/api/recording/delete、/api/epg/update、/api/settings。
设置（容量上限/保存文件夹）持久化于 base_dir/settings.json（record.save_settings）。
安全模型与服务本体一致：仅限局域网、无鉴权、禁止映射公网。
"""
import json
import os
import urllib.parse

import epg

PAGE = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>无双IPTV录像工具 · 管理</title>
<style>
body{font:14px/1.6 "Microsoft YaHei UI",system-ui,sans-serif;margin:0;background:#f2f5fa;color:#1f2937}
header{background:#2563eb;color:#fff;padding:10px 16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
header h1{font-size:16px;margin:0}
#stat{font-size:12px}
main{max-width:1100px;margin:12px auto;padding:0 12px}
section{background:#fff;border-radius:8px;padding:12px 14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h2{font-size:14px;margin:0 0 8px;color:#2563eb}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:5px 6px;border-bottom:1px solid #e6ebf2;white-space:nowrap}
th{color:#64748b;font-weight:600}
button{background:#2563eb;color:#fff;border:0;border-radius:5px;padding:4px 10px;cursor:pointer;font-size:12px}
button.gray{background:#64748b}button.red{background:#dc2626}
button:disabled{opacity:.5;cursor:default}
input,select{border:1px solid #cbd5e1;border-radius:5px;padding:4px 6px;font-size:13px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.hint{color:#64748b;font-size:12px}
a{color:#2563eb}
</style>
</head>
<body>
<header><h1>无双IPTV录像工具 · Web 管理</h1><div id="stat">加载中…</div></header>
<div style="background:#fef2f2;color:#b91c1c;padding:8px 16px;font-size:13px">⚠ 本工具仅供个人研究学习使用，请在 24 小时内删除录制文件。传播录制文件会导致版权风险，该风险与本软件无关。</div>
<main>
<section><h2>状态与设置</h2>
<div id="active" class="hint">未在录制</div>
<div class="row">容量上限(GB)<input id="setQuota" type="number" min="0" step="10" style="width:80px">
保存文件夹<input id="setDir" style="width:340px">
<button onclick="applySettings()">应用设置</button></div>
<div class="hint" id="setHint"></div>
<div class="hint">Docker 部署：文件夹须位于挂载卷内（挂载根见上方提示）；改挂 NAS 其它共享文件夹请改 compose 的 IPTV_RECORD_DIR 后重启容器。超出上限自动清理最旧已完成录像（不删在录/待录）。</div>
</section>
<section><h2>预约录像</h2>
<div class="row">频道<select id="schCh"></select>
<label><input type="radio" name="mode" value="manual" checked onchange="modeChg()"> 手动时间段</label>
<label><input type="radio" name="mode" value="epg" onchange="modeChg()"> 按节目</label></div>
<div class="row" id="mManual">日期<input id="schDate" type="date">
开始<input id="schT1" type="time" value="19:30"> 结束<input id="schT2" type="time" value="21:30"></div>
<div class="row" id="mEpg" style="display:none">节目关键词<input id="schTitle" placeholder="如 新闻联播 / 英超">
<button class="gray" onclick="loadProgs()">查节目</button><select id="schProg" style="max-width:420px"></select></div>
<div class="row"><button onclick="addSch()">添加预约</button>
<button class="gray" id="epgBtn" onclick="epgUpdate()">更新节目单</button><span id="epgLbl" class="hint"></span></div>
<table><thead><tr><th>频道</th><th>节目</th><th>开始</th><th>结束</th><th>状态</th><th></th></tr></thead><tbody id="schs"></tbody></table>
</section>
<section><h2>录像（播放链接可在 VLC / Kodi / TiviMate / KmPlayer 打开拖动）</h2>
<table><thead><tr><th>开始</th><th>频道/节目</th><th>时长</th><th>大小</th><th>状态</th><th>操作</th></tr></thead><tbody id="recs"></tbody></table>
</section>
<section><h2>频道与录制</h2>
<div class="row">录制时长(分钟)<input id="mins" type="number" value="60" min="1" style="width:70px">
<span class="hint">点频道行「录制」立即开录；多路并发上限由服务配置决定</span></div>
<table><thead><tr><th>频道</th><th>组播</th><th>分类</th><th>状态</th><th></th></tr></thead><tbody id="chs"></tbody></table>
</section>
<p class="hint">仅限局域网，禁止映射公网；本页面与转发服务同信任模型（无鉴权）。录像仅供个人观看。</p>
</main>
<script>
const $=id=>document.getElementById(id);
const fmtB=n=>n>=1073741824?(n/1073741824).toFixed(2)+' GB':n>=1048576?(n/1048576).toFixed(1)+' MB':((n/1024)|0)+' KB';
const fmtD=s=>{s=s|0;const p=x=>String(x).padStart(2,'0');return p(s/3600|0)+':'+p(s%3600/60|0)+':'+p(s%60)};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(p,b){const r=await fetch(p,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined);return r.json()}
let CH=[],RECS=[],SCHS=[],PROGS=[],dirty=false;
function modeChg(){const m=document.querySelector('input[name=mode]:checked').value;
$('mManual').style.display=m==='manual'?'flex':'none';$('mEpg').style.display=m==='epg'?'flex':'none'}
async function refresh(){
 let d;try{d=await api('/api/state')}catch(e){return}
 if(!d.ok)return;
 CH=d.channels||[];RECS=(d.recordings||[]).slice().sort((a,b)=>(b.start||'').localeCompare(a.start||''));
 SCHS=(d.schedules||[]).slice().sort((a,b)=>(a.start||'').localeCompare(b.start||''));
 const st=d.status;
 $('stat').textContent='录像 '+st.recordings+' · 待录 '+st.pending+' · 配额 '+st.quota_used_gb+'/'+(st.quota_gb||'∞')+' GB';
 $('active').innerHTML=st.active.length?st.active.map(a=>'<div class="row">⏺ '+esc(a.name)+' '+fmtD(a.duration)+' / '+fmtB(a.bytes)+' <button class="red" onclick="stopRec(\''+a.rid+'\')">停止</button></div>').join(''):'未在录制';
 if(!dirty){$('setQuota').value=st.quota_gb;$('setDir').value=d.settings.record_dir}
 const gph=st.gb_per_hour;
 $('setHint').textContent='每小时每频道约 '+(gph?gph+' GB（实测均值）':'1~4 GB（高清经验值）')+'；标清 1~2、4K 15~22 GB/小时。挂载根: '+d.settings.base_dir;
 const sel=$('schCh');const keep=sel.value;
 sel.innerHTML=CH.map((c,i)=>'<option value="'+i+'">'+esc(c.name)+'</option>').join('');
 if(keep&&keep<CH.length)sel.value=keep;
 $('recs').innerHTML=RECS.map((r,i)=>'<tr><td>'+esc((r.start||'').replace('T',' '))+'</td><td>'+esc(r.name)+(r.epg_title?' '+esc(r.epg_title):'')+'</td><td>'+fmtD(r.duration)+'</td><td>'+fmtB(r.bytes)+'</td><td>'+esc(r.status)+'</td><td><a href="/vod/'+encodeURIComponent(r.id)+'" target="_blank">播放</a> '+(r.status==='recording'?'<button class="red" onclick="stopRec(\''+r.id+'\')">停止</button> ':'')+'<button class="gray" onclick="delRecIdx('+i+')">删除</button></td></tr>').join('')||'<tr><td colspan="6" class="hint">暂无录像</td></tr>';
 const SM={pending:'待录',recording:'⏺ 录制中',done:'✓ 完成',missed:'错过',canceled:'已取消',error:'✗ 错误',partial:'◐ 部分'};
 $('schs').innerHTML=SCHS.map((s,i)=>'<tr><td>'+esc(s.channel.name)+'</td><td>'+esc(s.epg_title||'')+'</td><td>'+esc((s.start||'').replace('T',' '))+'</td><td>'+esc((s.end||'').replace('T',' '))+'</td><td>'+(SM[s.status]||s.status)+'</td><td>'+(s.status==='pending'||s.status==='recording'?'<button class="gray" onclick="cancelSchIdx('+i+')">取消</button>':'')+'</td></tr>').join('')||'<tr><td colspan="6" class="hint">暂无预约</td></tr>';
 $('chs').innerHTML=CH.map((c,i)=>'<tr><td>'+esc(c.name)+'</td><td>'+esc(c.group)+':'+c.port+'</td><td>'+esc(c.cat||'')+'</td><td>'+(c.ok?'✓ 可用':'未验证')+'</td><td><button onclick="startRecIdx('+i+')">录制</button></td></tr>').join('')||'<tr><td colspan="5" class="hint">无频道：服务启动时请加 --channels 频道文件</td></tr>';
 if(d.epg&&d.epg.updated)$('epgLbl').textContent='节目单 '+d.epg.updated+' · 映射 '+d.epg.mapped+' 频道';
}
async function applySettings(){
 const q=parseFloat($('setQuota').value);const rd=$('setDir').value.trim();
 if(isNaN(q)||q<0)return alert('容量上限须为非负数字');
 const r=await api('/api/settings',{quota_gb:q,record_dir:rd});
 if(!r.ok)return alert(r.error);
 dirty=false;refresh()}
async function startRecIdx(i){const c=CH[i];const mins=parseFloat($('mins').value)||60;
 const r=await api('/api/record/start',{group:c.group,port:c.port,name:c.name,seconds:Math.round(mins*60)});
 if(!r.ok)alert(r.error);refresh()}
async function stopRec(rid){const r=await api('/api/record/stop',{rid:rid});if(!r.ok)alert(r.error);refresh()}
async function delRecIdx(i){const r=RECS[i];if(!confirm('删除录像 '+r.name+' '+(r.start||'')+'？不可恢复。'))return;
 const d=await api('/api/recording/delete',{id:r.id});if(!d.ok)alert(d.error);refresh()}
async function cancelSchIdx(i){const d=await api('/api/schedule/cancel',{id:SCHS[i].id});if(!d.ok)alert(d.error);refresh()}
async function loadProgs(){const c=CH[+$('schCh').value];if(!c)return alert('先选频道');
 const d=await api('/api/programs?name='+encodeURIComponent(c.name));PROGS=d.programs||[];
 $('schProg').innerHTML=PROGS.map((p,i)=>'<option value="'+i+'">'+esc(p.start.slice(5,16).replace('T',' '))+' '+esc(p.title)+'</option>').join('')||'<option value="">（无节目，请先更新节目单）</option>'}
async function addSch(){const c=CH[+$('schCh').value];if(!c)return alert('先选频道');
 const m=document.querySelector('input[name=mode]:checked').value;let b;
 if(m==='epg'){const p=PROGS[+$('schProg').value];if(!p)return alert('先查节目并选择');
  b={group:c.group,port:c.port,name:c.name,title:p.title,date:p.start.slice(0,10)}}
 else{const d=$('schDate').value;if(!d)return alert('选日期');
  b={group:c.group,port:c.port,name:c.name,start:d+'T'+$('schT1').value,end:d+'T'+$('schT2').value}}
 const r=await api('/api/schedule/add',b);if(!r.ok)alert(r.error);else refresh()}
async function epgUpdate(){$('epgBtn').disabled=true;$('epgLbl').textContent='更新中…（主动联网）';
 try{const r=await api('/api/epg/update',{});
  $('epgLbl').textContent=r.ok?('更新完成：映射 '+r.mapped+' 频道 / '+r.programmes+' 节目'):('失败: '+r.error)}
 catch(e){$('epgLbl').textContent='失败: '+e}
 $('epgBtn').disabled=false;refresh()}
$('schDate').value=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
$('setQuota').addEventListener('input',()=>dirty=true);
$('setDir').addEventListener('input',()=>dirty=true);
refresh();setInterval(refresh,2000);
</script>
</body>
</html>
'''


def _json(handler, obj, code=200):
    handler._send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                  'application/json')


def _settings(mgr):
    return {'quota_gb': mgr.quota_gb, 'record_dir': mgr.record_dir,
            'base_dir': mgr.base_dir}


def handle_get(handler, outer, path):
    mgr = outer.record_mgr
    params = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    if path == '/api/state':
        d = epg.load(mgr.record_dir) or {}
        recs = mgr.list_recordings()
        st = mgr.status()
        measured = [r for r in recs if (r.get('duration') or 0) > 60 and r.get('bytes')]
        st['gb_per_hour'] = round(
            sum(r['bytes'] for r in measured) / sum(r['duration'] for r in measured)
            * 3600 / 1024 ** 3, 2) if measured else None
        _json(handler, {'ok': True, 'channels': outer.channels_cb(),
                        'recordings': recs,
                        'schedules': mgr.list_schedules(),
                        'status': st, 'settings': _settings(mgr),
                        'epg': {'updated': d.get('updated', ''),
                                'source': d.get('source', ''),
                                'mapped': len(d.get('channels', {}))}})
    elif path == '/api/programs':
        name = (params.get('name') or [''])[0]
        _json(handler, {'ok': True, 'programs': epg.programs(mgr.record_dir, name)})
    else:
        handler.send_error(404)


def handle_post(handler, outer, path, body):
    mgr = outer.record_mgr
    try:
        req = json.loads(body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        _json(handler, {'ok': False, 'error': 'invalid JSON'}, 400)
        return
    try:
        if path == '/api/record/start':
            ch = {'name': req.get('name') or '', 'group': req['group'],
                  'port': int(req['port'])}
            sch = mgr.record_now(ch, seconds=int(req.get('seconds') or 3600))
            _json(handler, {'ok': True, 'schedule': sch})
        elif path == '/api/record/stop':
            sid = req.get('sid')
            if not sid:
                for s in mgr.list_schedules():
                    if s.get('rid') == req.get('rid') and s['status'] == 'recording':
                        sid = s['id']
                        break
            if not sid:
                raise ValueError('未找到在录录像: %s' % req.get('rid'))
            mgr.cancel(sid)
            _json(handler, {'ok': True})
        elif path == '/api/schedule/add':
            ch = {'name': req.get('name') or '', 'group': req['group'],
                  'port': int(req['port'])}
            if req.get('title'):
                p = epg.find_next(mgr.record_dir, ch['name'], req['title'], req.get('date'))
                if not p:
                    raise ValueError('EPG 中未找到节目: %s（先更新节目单）' % req['title'])
                sch = mgr.add_schedule(ch, p['start'], p['stop'],
                                       source='epg', epg_title=p['title'])
            else:
                sch = mgr.add_schedule(ch, req['start'], req['end'])
            _json(handler, {'ok': True, 'schedule': sch})
        elif path == '/api/schedule/cancel':
            mgr.cancel(req['id'])
            _json(handler, {'ok': True})
        elif path == '/api/recording/delete':
            mgr.delete_recording(req['id'])
            _json(handler, {'ok': True})
        elif path == '/api/epg/update':
            _json(handler, epg.update(mgr.record_dir, outer.channels_cb()))
        elif path == '/api/settings':
            import record  # 延迟导入避免 proxy↔webui↔record 循环
            q = req.get('quota_gb')
            if q is not None:
                q = float(q)
                if q < 0:
                    raise ValueError('容量上限不能为负')
            rd = (req.get('record_dir') or '').strip()
            if rd and os.path.abspath(rd) != mgr.record_dir:
                if mgr.status()['active']:
                    raise ValueError('有录制进行中，请先停止再改保存文件夹')
                try:
                    os.makedirs(os.path.join(rd, 'ts'), exist_ok=True)
                except OSError as e:
                    raise ValueError('无法创建文件夹（Docker 下须在挂载卷内）: %s' % e)
                new = record.RecordManager(
                    rd, mgr.iface_ip, channels_cb=outer.channels_cb,
                    quota_gb=q if q is not None else mgr.quota_gb,
                    pad_before=mgr.pad_before, pad_after=mgr.pad_after,
                    max_concurrent=mgr.max_concurrent,
                    missed_policy=mgr.missed_policy, scheduler=True)
                new.start()
                mgr.save_settings(quota_gb=q, record_dir=rd)
                new.save_settings(quota_gb=q, record_dir=rd)
                mgr.stop()
                outer.record_mgr = new
            elif q is not None:
                mgr.save_settings(quota_gb=q)
            _json(handler, {'ok': True, 'settings': _settings(outer.record_mgr)})
        else:
            handler.send_error(404)
    except Exception as e:
        _json(handler, {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
