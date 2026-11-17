# -*- coding: utf-8 -*-
"""接线向导：硬件问卷 → 定制化插拔网线指导 + 拓扑图数据。
经验（实测总结）：
- 傻瓜交换机无 IGMP snooping，组播泛洪到所有口，PC 有线口才能"搭线"收流；
- PC 有线口进 ITV 专网后拿不到 DHCP（169.254.x）属正常；
- 上网保持走 WiFi（连家里路由器）；
- 抓完可选"桥接合并"：路由器 LAN 也插交换机 → 全家设备直看组播；
  合并后机顶盒可能从路由器拿错 IP 导致认证失败，拔桥接线即可回滚。
"""

QUESTIONS = [
    {'id': 'mode', 'text': '你现在的情况是？',
     'options': [('fresh', '第一次抓源：机顶盒还在用，准备搭线抓包（需傻瓜交换机）'),
                 ('router', '路由器带 IPTV 口/VLAN 绑定：路由里设置 IPTV 口，免交换机'),
                 ('merged', '已按教程把 IPTV 桥接进局域网（机顶盒已退役）'),
                 ('manual', '只想手动管理/验证频道列表，不抓包')]},
    {'id': 'pc_lan', 'text': '电脑有有线网口（LAN 口）吗？',
     'options': [('yes', '有，主板/机箱自带网口'),
                 ('usb', '没有，但有 USB 有线网卡'),
                 ('no', '没有，只有 WiFi')]},
    {'id': 'pc_wifi', 'text': '电脑有 WiFi 吗？（抓包时上网要靠它）',
     'options': [('yes', '有 WiFi'), ('no', '没有 WiFi')]},
    {'id': 'switch', 'text': '交换机是什么情况？',
     'options': [('dumb3', '有 3 口以上的傻瓜交换机（普通无管理功能）'),
                 ('dumb2', '只有 2 口交换机 / 网线直通头'),
                 ('managed', '有交换机，但是带管理功能（网管型）'),
                 ('none', '没有交换机')]},
    {'id': 'stb_lan', 'text': '机顶盒有网口吗？',
     'options': [('yes', '有网口，现在接着网线'),
                 ('wifi', '机顶盒只用 WiFi / 没有网口'),
                 ('retired', '机顶盒已退役不用了')]},
    {'id': 'ont_port', 'text': '光猫的 IPTV 口（ITV 口）是哪个？',
     'options': [('itv', '有专门标注 ITV/IPTV 的口'),
                 ('lan2', 'LAN2 口'), ('lan1', 'LAN1 口'),
                 ('lan3', 'LAN3 口'), ('lan4', 'LAN4 口'),
                 ('unknown', '不清楚')]},
    {'id': 'router_wan', 'text': '路由器的 WAN 口现在接在哪里？（上网线路，保持不动）',
     'options': [('ont', '光猫的上网口（LAN1/千兆口）'),
                 ('wall', '墙上弱电箱来的网线（光猫在弱电箱）'),
                 ('none', '没有路由器，电脑直接拨号/接光猫'),
                 ('other', '其他/不清楚')]},
    {'id': 'router_iptv', 'text': '【路由器 IPTV 场景】路由器支持 IPTV 口/VLAN 绑定吗？',
     'options': [('yes', '支持，已在路由里设置/可设置 IPTV 口'),
                 ('unsure', '不确定，需要指导怎么找'),
                 ('no', '不支持 / 是普通老路由')]},
    {'id': 'router_igmp', 'text': '【路由器 IPTV 场景】路由里有 IGMP Proxy/组播转发/组播增强 选项吗？',
     'options': [('yes', '有，可以开启'),
                 ('unsure', '不确定'),
                 ('no', '没有')]},
]

ONT_LABEL = {'itv': '光猫 ITV 口', 'lan2': '光猫 LAN2（ITV）口', 'lan1': '光猫 LAN1（ITV）口',
             'lan3': '光猫 LAN3（ITV）口', 'lan4': '光猫 LAN4（ITV）口',
             'unknown': '光猫 ITV 口（待确认）'}


def build_plan(ans):
    """返回 {ok, blockers, warnings, steps:[{title,detail}], bridge_steps, topology}"""
    mode = ans.get('mode', 'fresh')
    blockers, warnings, steps = [], [], []
    ont = ONT_LABEL.get(ans.get('ont_port', 'unknown'), '光猫 ITV 口')

    if mode == 'manual':
        return {'ok': True, 'blockers': [], 'warnings': [],
                'steps': [{'title': '无需接线',
                           'detail': '直接到「频道验证」页：添加/导入频道 → 选择网卡 → 验证 → 生成 M3U。'}],
                'bridge_steps': [], 'topology': 'none'}
    if mode == 'merged':
        steps.append({'title': '确认桥接现状',
                      'detail': '确认：光猫 ITV 口 → 傻瓜交换机 → 路由器 LAN（桥接线）仍在，交换机通电。'
                                '此时组播已进入家庭局域网，无需机顶盒。'})
        steps.append({'title': '确认电脑有线口',
                      'detail': '电脑有线口接在交换机/路由器 LAN 上，ipconfig（Linux/macOS 用 ifconfig 或 ip addr）'
                                '应能看到 192.168.x.x（路由器分配）。若只有 WiFi 也能验证，但建议有线。'})
        steps.append({'title': '直接载入参考库',
                      'detail': '到「频道验证」页：点「选择地区载入参考库」→ 选你的省份+运营商 → 验证全部 → 生成 M3U。'
                                '参考库覆盖全国 31 省×电信/联通/移动/广电（社区共享，浙江电信经实测校验）。'})
        warnings.append('若日后重新接回电信机顶盒：它可能从路由器拿到错误 IP 导致 IPTV 认证失败，'
                        '拔掉「路由器 LAN → 交换机」桥接线即可恢复隔离。')
        return {'ok': True, 'blockers': [], 'warnings': warnings, 'steps': steps,
                'bridge_steps': [], 'topology': 'merged'}

    # ---- router：路由器 IPTV 口/VLAN 绑定，免交换机 ----
    if mode == 'router':
        if ans.get('pc_lan') == 'no':
            blockers.append('电脑没有有线网口：抓包/加组需要有线接入。请用一个 USB 有线网卡。')
        if ans.get('router_iptv') == 'no':
            blockers.append('路由器不支持 IPTV 口/VLAN 绑定：此场景不适用。请改选「第一次抓源（搭线）」'
                            '用傻瓜交换机，或换一台支持 IPTV 的路由器。')
        if ans.get('router_iptv') == 'unsure':
            warnings.append('不确定是否支持：进路由管理页找「IPTV / VLAN / 单线复用 / 端口绑定」字样'
                            '（TP-Link/华为/小米/华硕 等多数新款都有）。找不到就按不支持处理，改用搭线法。')
        if ans.get('router_igmp') in ('no', 'unsure'):
            warnings.append('若路由没有/未开 IGMP Proxy·组播转发：组播可能只留在 IPTV 口、不进普通 LAN。'
                            '此时把电脑也接到被绑定为 IPTV 的口（若支持多口），或在该 IPTV 口下接傻瓜交换机'
                            '分给机顶盒+电脑（回退搭线法）。')
        if ans.get('stb_lan') == 'retired':
            warnings.append('机顶盒已退役：无需抓包，直接在「频道验证」载入参考库，电脑有线口加组实测即可。')
        steps.append({
            'title': '第 1 步 · 确认光猫 ITV / VLAN',
            'detail': '单线复用（光猫一根线到路由 WAN）需知道 ITV 的 VLAN ID（光猫后台或问装维）。'
                      '若光猫有独立 ITV 口，也可用网线把 ITV 口接到路由 WAN/指定口，按路由说明绑定。'})
        steps.append({
            'title': '第 2 步 · 路由里绑定 IPTV 口',
            'detail': '进路由管理 → IPTV/VLAN 设置 → 启用并填入 ITV VLAN（或选择桥接模式）→ 把某个 LAN 口'
                      '（如 LAN4）绑定为 IPTV 口 → 保存。该口此后属于 ITV 专网，不再是普通 LAN。'})
        steps.append({
            'title': '第 3 步 · 机顶盒接 IPTV 口',
            'detail': '把机顶盒网线插到刚绑定的 IPTV 口（LAN4），开机应能正常看直播，说明绑定成功。'})
        steps.append({
            'title': '第 4 步 · 电脑接普通 LAN 口',
            'detail': '电脑有线口接路由器普通 LAN 口（保持能上网）。无需傻瓜交换机、无需改光猫接线。'})
        steps.append({
            'title': '第 5 步 · 开启组播转发（如有）',
            'detail': '若路由有 IGMP Proxy / 组播转发 / 组播增强 / Multicast Enhancement：开启它。'
                      '开启后组播进入整个局域网，电脑在普通 LAN 口即可抓包/加组验证，最方便。'})
        steps.append({
            'title': '第 6 步 · 抓包或验证',
            'detail': '组播已在 LAN：到「抓包分析」开始抓包并让机顶盒换台，或直接「频道验证」载入参考库实测。'
                      '组播不在 LAN：把电脑改接到另一个 IPTV 绑定口（若支持），或在该 IPTV 口下接傻瓜交换机'
                      '分给机顶盒+电脑，再抓包。'})
        return {'ok': not blockers, 'blockers': blockers, 'warnings': warnings,
                'steps': steps if not blockers else [], 'bridge_steps': [],
                'topology': 'router' if not blockers else 'none', 'ont_label': ont}

    # ---- fresh：搭线抓包 ----
    if ans.get('pc_lan') == 'no':
        blockers.append('电脑没有有线网口：WiFi 看不到 ITV 专网的组播。请买一个 USB 有线网卡（几十元）后再来。')
    if ans.get('pc_wifi') == 'no':
        warnings.append('电脑没有 WiFi：搭线后有线口进了 ITV 专网，电脑将暂时无法上网（不影响抓包）。'
                        '建议抓包时用手机热点 USB 共享，或抓完恢复接线。')
    sw = ans.get('switch')
    if sw == 'none':
        blockers.append('没有交换机：无法把「光猫 ITV 口、机顶盒、电脑」三方接在一起。'
                        '请准备一台 3 口以上傻瓜交换机（普通家用交换机即可，几十元）。')
    elif sw == 'dumb2':
        blockers.append('2 口交换机/直通头不够：需要同时接光猫 ITV、机顶盒、电脑三方，至少 3 口。')
    elif sw == 'managed':
        warnings.append('网管型交换机可能开启 IGMP Snooping，只把组播发给机顶盒，电脑抓不到。'
                        '请在交换机设置里关闭 IGMP Snooping，或换傻瓜交换机。')
    if ans.get('stb_lan') == 'wifi':
        blockers.append('机顶盒没有网口：无法用交换机搭线触发加组。可选：① 若已桥接合并网络，选「已桥接」模式用参考库；'
                        '② 手动添加频道后逐个验证。')
    elif ans.get('stb_lan') == 'retired':
        warnings.append('机顶盒已退役：抓包需要机顶盒开机换台来"点播"组播地址。'
                        '请临时把机顶盒接回交换机并通电；若不想接回，可改用「已桥接」模式 + 参考库。')
    if ans.get('ont_port') == 'unknown':
        warnings.append('不确定 ITV 口：看光猫背面标签，通常标注 ITV/IPTV，常见为 LAN2。'
                        '也可逐个 LAN 口试：抓包时若出现 192.168.1.1 的 IGMP 查询或 10.x 的 DHCP，即为 ITV 口。')
    if ans.get('router_wan') == 'none':
        warnings.append('没有路由器：抓包不受影响，但「桥接合并」与 HTTP 转发给其他设备的功能需要局域网，建议加一台路由器。')

    steps.append({
        'title': '第 1 步 · 记录原接线',
        'detail': '先拍照记录机顶盒网线原来插在哪（墙上 ITV 口 / 光猫 %s）。这根线就是 IPTV 信号线，后面要用。'
                  '然后关闭机顶盒电源，拔下机顶盒端的网线。' % ont})
    steps.append({
        'title': '第 2 步 · 摆放傻瓜交换机',
        'detail': '把傻瓜交换机放在电视柜附近并通电。确认它是普通无管理交换机（无 IGMP Snooping，组播会泛洪到所有口）。'})
    steps.append({
        'title': '第 3 步 · IPTV 信号线 → 交换机口 1',
        'detail': '把第 1 步那根 IPTV 信号线（墙端/光猫端不动，仍插在 %s）的另一端，插到交换机口 1。' % ont})
    steps.append({
        'title': '第 4 步 · 机顶盒 → 交换机口 2',
        'detail': '用另一根网线，把机顶盒网口接到交换机口 2。机顶盒先不通电。'})
    pc_port = 'USB 网卡' if ans.get('pc_lan') == 'usb' else '电脑有线口'
    steps.append({
        'title': '第 5 步 · %s → 交换机口 3' % pc_port,
        'detail': '把电脑有线口（若原来插着家里上网的网线，先拔下）用网线接到交换机口 3。'
                  '注意：此时电脑有线口进入 IPTV 专网，可能显示"无 Internet / 169.254.x.x"，这是正常现象！'})
    if ans.get('pc_wifi') == 'yes':
        steps.append({
            'title': '第 6 步 · 保持 WiFi 上网',
            'detail': '电脑 WiFi 保持连接家里路由器，上网不受影响。路由器 WAN → 光猫上网口的线保持不动。'})
    else:
        steps.append({
            'title': '第 6 步 · 上网说明',
            'detail': '电脑没有 WiFi，抓包期间暂时无法上网，属正常。抓完恢复原接线即可。'})
    steps.append({
        'title': '第 7 步 · 机顶盒通电开机',
        'detail': '给机顶盒通电开机，等它进入直播画面。然后到「抓包分析」页点「开始抓包」，'
                  '用遥控器逐个换台（每个频道停 3~5 秒），换完点「停止并分析」。'})

    bridge_steps = [
        {'title': '可选进阶 · 桥接合并（全家直看组播）',
         'detail': '抓源完成后，若想让全家设备不依赖任何服务直接播放 udp:// 组播地址：'
                   '再拿一根网线，把交换机空口（口 4）接到路由器 LAN 口（或通往弱电箱路由器 LAN 的墙口）。'
                   '两网二层合并后，组播进入家庭局域网。'},
        {'title': '合并后的注意事项',
         'detail': '① IPTV 的 DHCP+ 服务器不响应普通设备，不会抢路由器 DHCP（实测安全）；'
                   '② 机顶盒此时可能从路由器拿到错误 IP 导致认证失败——建议机顶盒退役，或拔掉桥接线恢复隔离；'
                   '③ WiFi 播放组播卡顿的话，用本工具「转发服务」页的 HTTP 单播通道。'},
    ]
    if blockers:
        return {'ok': False, 'blockers': blockers, 'warnings': warnings,
                'steps': [], 'bridge_steps': [], 'topology': 'none'}
    return {'ok': True, 'blockers': [], 'warnings': warnings, 'steps': steps,
            'bridge_steps': bridge_steps, 'topology': 'tap', 'ont_label': ont}
