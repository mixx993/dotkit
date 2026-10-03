"""自动导演：素材统计（meta.json）+ 节拍（beats.json）→ 一份可以直接改的剪辑脚本 edit.py。

段落模板来自参考片《点之战》（按片长等比缩放，边界吸附到拍点 / 重拍上）：
  闪现 → 色散 → 炸向镜头 → 从大点拉出 → 节拍轮换 → 定格环绕 → 扯散 → 彩色残影 → 加速 → 终炸 → 消散
片长不到 8 秒时去掉 拉出 / 扯散 / 残影。

生成的是普通 Python，每段一行 E.shot(...)，带注释；想改哪段直接改。
"""
import json, os
import numpy as np


def _strongest(b, t0, t1, default):
    c = [(s, t) for t, s in zip(b.get('hits', []), b.get('hit_strength', [])) if t0 <= t <= t1]
    return max(c)[1] if c else default


def _snap(b, t, key='beats'):
    xs = b.get(key) or []
    return min(xs, key=lambda x: abs(x - t)) if xs else t


def plan(meta, b, dur, sync=True, style='auto'):
    """返回段落时间表 + 风格决定（dict），write_script 用它生成代码。"""
    D = dur
    beats = b.get('beats') or list(np.arange(0, D, 0.5))
    P = float(np.median(np.diff(beats))) if len(beats) > 2 else 0.5
    dark = meta.get('fg_luma_mean', 0.5) < 0.33 or meta.get('fg_luma_std', 0.2) < 0.12
    if style != 'auto': dark = style == 'dark'
    short = D < 8
    nclip = meta['frames']
    s = {}
    s['intro'] = _strongest(b, 0.05 * D, 0.12 * D, _snap(b, 0.07 * D))
    s['intro'] = max(s['intro'], 0.6)
    s['explode'] = (s['intro'] + 2 / 24, _snap(b, s['intro'] + max(0.45, 1.3 * P)))
    if s['explode'][1] - s['explode'][0] < 0.35: s['explode'] = (s['explode'][0], s['explode'][0] + 0.45)
    s['pullout'] = None if short else (s['explode'][1], _snap(b, s['explode'][1] + max(0.6, 2 * P)))
    cyc0 = s['pullout'][1] if s['pullout'] else s['explode'][1]
    fz = _strongest(b, 0.42 * D, 0.6 * D, _snap(b, 0.5 * D))
    fz = max(fz, cyc0 + 4 * P)
    s['cycle'] = (cyc0, fz)
    fz_len = max(1.4, min(0.12 * D, 2.6))
    s['freeze'] = (fz, _snap(b, fz + fz_len))
    t = s['freeze'][1]
    if short:
        s['stream'] = s['trails'] = None
        acc0 = t
    else:
        s['stream'] = (t, _snap(b, t + max(0.9, 0.07 * D)))
        t = s['stream'][1]
        acc0 = _snap(b, max(t + 1.5, 0.82 * D))
        s['trails'] = (t, acc0)
    fin = _strongest(b, max(acc0 + 0.6, 0.86 * D), 0.94 * D, _snap(b, 0.9 * D))
    fin = min(fin, D - 0.8)                      # 终炸至少留 0.45 秒，消散至少 0.35 秒
    s['accel'] = (acc0, fin)
    s['final'] = (fin, min(D - 0.35, fin + 0.6))
    s['dissolve'] = (s['final'][1], D)
    # 定格用哪一帧：定格时刻 ±0.3 秒里人物面积最大的一帧（不在镜头切点上）
    f0 = int(round(fz * 24)) if sync else 0
    area = meta.get('area') or [0.3] * nclip
    cuts = set(meta.get('cuts', []))
    cands = [f for f in range(max(0, f0 - 7), min(nclip, f0 + 8)) if f not in cuts and f % nclip == f]
    s['freeze_src'] = max(cands, key=lambda f: area[f]) if cands else min(f0, nclip - 1)
    s['final_src'] = min(int(round(fin * 24)), nclip - 1) if sync else nclip // 2
    s['cuts'] = [c / 24 for c in meta.get('cuts', []) if 0 < c / 24 < D]
    return dict(D=D, P=P, switch='halves' if P >= 0.4 else 'beats', dark=dark, sec=s, sync=sync)


def write_script(path, clip_dir, beats_path, audio, pl):
    s, D = pl['sec'], pl['D']
    f = lambda x: f'{x:.2f}'
    rel = lambda p: os.path.relpath(os.path.abspath(p), os.path.dirname(os.path.abspath(path)))
    L = []
    w = L.append
    w('"""自动导演生成的剪辑脚本（dotkit auto）。直接改，然后：python edit.py   或   python edit.py --frames 120 180"""')
    w('import os')
    w('from dotkit import Edit, Cam, Look, LOOKS, TRAIL, replace')
    w('')
    w('HERE = os.path.dirname(os.path.abspath(__file__))')
    w(f"SRC = os.path.join(HERE, {rel(clip_dir)!r})")
    w(f"AUDIO = os.path.join(HERE, {rel(audio)!r})" if audio else 'AUDIO = None')
    w(f"E = Edit(os.path.join(HERE, {rel(beats_path)!r}), dur={D:.2f})")
    w('F = 1 / 24')
    w('')
    if pl['dark']:
        w('# 素材偏暗 / 偏灰（比如黑衣服、灰背景）：全部开 levels（人物内拉色阶），原色点换成钢蓝 → 暖白双色')
        w("L = {k: replace(v, levels=1.0) for k, v in LOOKS.items()}")
        w("L['base'] = Look(bg='#05060A', color='duo', c1='#26315C', c2='#F4E9D6', spacing=8, size=0.5, levels=1.0)")
        w("L['coarse'] = Look(bg='#000000', color='duo', c1='#2A3566', c2='#F6E7D2', spacing=64, size=0.47, levels=1.0, fg_only=False, bg_dot='#C9422F', bg_size=0.3)")
        w("L['final'] = Look(bg='#030303', color='duo', c1='#C9422F', c2='#F6E7D2', spacing=8, size=0.5, levels=1.0)")
    else:
        w("L = dict(LOOKS)")
        w("L['base'] = LOOKS['orig_dense']")
        w("L['coarse'] = LOOKS['orig_coarse']")
        w("L['final'] = replace(LOOKS['orig_mid'], spacing=8, size=0.5)")
    w('')
    pp = 'False' if pl['sync'] else 'True'
    w('def sync(t0, t1, **kw):')
    w('    """源画面跟着时间走（素材自带的声音才对得上）。"""')
    w(f"    return E.shot(t0, t1, SRC, src=t0 * 24, speed=1, pingpong={pp}, **kw)")
    w('')
    w("CYCLE = [L[k] for k in ['cream_navy', 'black_pink', 'gold_glow', 'base', 'yellow_black', 'white_sparse',")
    w("                       'blue_white', 'orig_mid', 'orange_black', 'purple_glow', 'cyan_black', 'magenta_white',")
    w("                       'white_navy', 'orange_blob']]")
    w('')
    t0 = s['intro']
    w(f'# A 0–{f(t0)}  原画，单帧点阵闪现，越来越密')
    w(f"sync(0, {f(t0)}, look=L['base'], raw=1)")
    n = int(t0 * 24)
    gl = sorted({int(n * (1 - 0.72 ** k)) for k in range(1, 12)} - {0, n})
    w(f"for f in {gl}:")
    w("    E.shot(f * F, (f + 1) * F, SRC, src=f, speed=0, look=replace(L['glimpse'], levels=0.6))")
    e0, e1 = s['explode']
    w(f'# B 色散 2 帧 → C 整个画面碎成点扑向镜头（{f(e0)}–{f(e1)}）')
    w(f"sync({f(t0)}, {f(e0)}, look=L['base'], raw=1, ca=22)")
    w(f"E.shot({f(e0)}, {f(e1)}, SRC, src={int(e0 * 24) if pl['sync'] else 0}, speed=0, look=replace(L['glimpse'], spacing=9, size=0.5, levels=0.6),")
    w("       cam=Cam(dof=3.0), shutter=4, anim={'explode': (0, 2600, 'out')})")
    if s['pullout']:
        a, bb = s['pullout']
        w(f'# D 从巨大的点里拉出来（{f(a)}–{f(bb)}）')
        w(f"sync({f(a)}, {f(bb)}, look=L['coarse'], cam=Cam(pivot=(0.5, 0.45)),")
        w("     anim={'zoom': (5.5, 1.0, 'out'), 'look.spacing': (90, 20, 'out')})")
    a, bb = s['cycle']
    w(f"# E 节拍轮换（{f(a)}–{f(bb)}），每{'半拍' if pl['switch'] == 'halves' else '拍'}换一个 look；重拍压扁 + 色散，最重的两下炸白光")
    w(f"sync({f(a)}, {f(bb)}, looks=CYCLE, switch={pl['switch']!r}, anim={{'zoom': (1.0, 1.08, 'lin')}})")
    w(f"E.hits_from_audio(kinds=('squash', 'ca'), t0={f(a)}, t1={f(bb - 0.05)}, min_strength=0.45)")
    w(f"for t, s in sorted(zip(E.b['hits'], E.b['hit_strength']), key=lambda x: -x[1]):")
    w(f"    if {f(a + 0.3)} < t < {f(bb - 0.3)}: E.hit(t, 'burst'); break")
    a, bb = s['freeze']
    mid = (a + bb) / 2
    fs = s['freeze_src']
    w(f'# F 定格 + 环绕（{f(a)}–{f(bb)}），停在源第 {fs} 帧；点云挤出厚度。只配密的 look（散点挤出后会变横线）')
    w(f"E.shot({f(a)}, {f(mid)}, SRC, src={fs}, speed=0, looks=[L['base'], L['black_pink'], L['orig_dense']], switch='beats',")
    w("       cam=Cam(depth=1300, extrude=120, extrude_n=6, pitch=5, pivot=(0.5, 0.55)), anim={'yaw': (-32, 8, 'inout')})")
    w(f"E.shot({f(mid)}, {f(bb)}, SRC, src={fs}, speed=0, looks=[L['black_salmon'], L['base']], switch='beats',")
    w("       cam=Cam(depth=1300, extrude=120, extrude_n=6, pivot=(0.5, 0.55)), anim={'yaw': (22, 32, 'lin'), 'zoom': (1.5, 1.7, 'lin')})")
    w(f"E.hit({f(a)}, 'flash').hit({f(a)}, 'ca')")
    if s['stream']:
        a, bb = s['stream']
        w(f'# G 回到实时，点被扯散、流走（{f(a)}–{f(bb)}）')
        w(f"sync({f(a)}, {f(bb)}, looks=[L['white_sparse'], L['purple_glow'], L['gold_glow'], L['orig_mid']], switch='beats',")
        w("     cam=Cam(dof=1.6, yaw=6), shutter=4, anim={'explode': (0, 1500, 'in')})")
    if s['trails']:
        a, bb = s['trails']
        w(f'# H 亮色底 + 彩色残影（{f(a)}–{f(bb)}），重拍炸白光')
        w("TR = dict(n=4, step=1, colors=TRAIL, alpha=0.7)")
        cuts = [c for c in s['cuts'] if a < c < bb]
        bounds = [a] + cuts + [bb]
        for x0, x1 in zip(bounds[:-1], bounds[1:]):
            floor = int(round(x0 * 24)) if pl['sync'] else 0
            w(f"sync({f(x0)}, {f(x1)}, looks=[L['blue_white'], L['orange_black'], L['magenta_white'], L['yellow_black'], L['cyan_black'], L['cream_navy']],")
            w(f"     switch='beats', trail={{**TR, 'floor': {floor}}})")
        w(f"E.hits_from_audio(kinds=('burst',), t0={f(a)}, t1={f(bb)}, min_strength=0.45)")
    for c in s['cuts']:
        if s['cycle'][0] < c < s['accel'][0] and not (s['freeze'][0] <= c < s['freeze'][1]):
            w(f'# 源素材在 {f(c)} 秒切镜头：原画 + 色散 + 白闪当转场')
            w(f"sync({f(c)}, {f(c + 0.17)}, look=L['base'], raw=1, ca=18); E.hit({f(c)}, 'flash')")
    a, bb = s['accel']
    w(f'# I 加速（{f(a)}–{f(bb)}），每半拍换')
    w(f"sync({f(a)}, {f(bb)}, looks=[L['white_sparse'], L['base'], L['yellow_black'], L['black_pink'], L['gold_glow'],")
    w("                         L['blue_white'], L['orig_mid'], L['magenta_white']], switch='halves')")
    w(f"E.hits_from_audio(kinds=('squash', 'ca'), t0={f(a)}, t1={f(bb - 0.05)}, min_strength=0.4)")
    a, bb = s['final']
    w(f'# J 终炸（{f(a)}–{f(bb)}）：放射状冲向镜头，运动模糊拉出放射线')
    w(f"E.shot({f(a)}, {f(bb)}, SRC, src={s['final_src']}, speed=0, look=L['final'], cam=Cam(dof=2.4), shutter=6,")
    w("       anim={'explode': (0, 3600, 'lin'), 'zoom': (1.0, 1.25, 'lin')})")
    w(f"E.hit({f(a)}, 'flash')")
    a, bb = s['dissolve']
    m = a + (bb - a) * 0.55
    w(f'# K 收尾（{f(a)}–{f(bb)}）：白点消散，只剩几个大白点')
    w(f"E.shot({f(a)}, {f(m)}, SRC, src={s['final_src']}, speed=0, look=L['white_sparse'],")
    w("       anim={'look.density': (0.45, 0.12, 'in'), 'look.spacing': (15, 34)})")
    w(f"E.shot({f(m)}, {f(bb)}, SRC, src={s['final_src']}, speed=0, look=L['white_bokeh'],")
    w("       anim={'look.density': (0.15, 0.04), 'look.spacing': (90, 140)})")
    w('')
    w("if __name__ == '__main__':")
    w("    E.run(HERE, audio=AUDIO, name='dots')")
    open(path, 'w').write('\n'.join(L) + '\n')
    return path


def describe(pl):
    s = pl['sec']
    rows = [('闪现', (0, s['intro'])), ('炸向镜头', s['explode']), ('拉出', s['pullout']), ('节拍轮换', s['cycle']),
            ('定格环绕', s['freeze']), ('扯散', s['stream']), ('彩色残影', s['trails']), ('加速', s['accel']),
            ('终炸', s['final']), ('消散', s['dissolve'])]
    out = [f"片长 {pl['D']:.2f}s  拍长 {pl['P']:.2f}s  轮换={'半拍' if pl['switch'] == 'halves' else '每拍'}  "
           f"{'暗素材模式(levels+双色)' if pl['dark'] else '原色模式'}  定格源帧 {s['freeze_src']}"]
    for name, r in rows:
        if r: out.append(f'  {r[0]:6.2f} – {r[1]:6.2f}  {name}')
    return '\n'.join(out)
