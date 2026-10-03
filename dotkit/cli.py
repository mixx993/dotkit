"""dotkit 命令行。

  dotkit doctor                                 检查环境（ffmpeg、torch 设备、能否 import）
  dotkit auto  VIDEO [--audio A] [--out DIR]    一条命令出片：预处理 → 测节拍 → 生成剪辑脚本 → 渲染 → 对照版
  dotkit prep  VIDEO OUT                        只做预处理（帧 + 遮罩 + 深度）
  dotkit beats AUDIO OUT.json                   只测节拍
  dotkit looks SRC_DIR [--frame N] [--out PNG]  把所有 look 画在同一帧上，拼一张对照图
  dotkit compare ORIGINAL PROCESSED OUT         上原画、下点阵的同屏对照
"""
import argparse, json, os, shutil, subprocess, sys


def _ok(msg): print(f'  OK   {msg}')
def _bad(msg): print(f'  FAIL {msg}')


def cmd_doctor(a):
    good = True
    for exe in ('ffmpeg', 'ffprobe'):
        if shutil.which(exe): _ok(exe)
        else: _bad(f'{exe} 不在 PATH 里（macOS: brew install ffmpeg；Ubuntu: apt install ffmpeg）'); good = False
    for mod in ('numpy', 'scipy', 'cv2', 'PIL', 'librosa'):
        try: __import__(mod); _ok(mod)
        except Exception as e: _bad(f'{mod}: {e}'); good = False
    try:
        import torch, transformers
        from .prep import device
        _ok(f'torch {torch.__version__} / transformers {transformers.__version__} / 设备 {device()}')
    except Exception as e:
        print(f'  WARN torch/transformers 不可用（{e}）——只能用 --mask key --depth flat')
    print('环境 OK' if good else '有问题，按上面的 FAIL 修')
    return 0 if good else 1


def cmd_prep(a):
    from .prep import prep
    prep(a.video, a.out, a.start, a.dur, a.mask, a.depth)


def cmd_beats(a):
    from .beats import analyze
    r = analyze(a.audio)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(r, open(a.out, 'w'), indent=1)
    print(f"tempo {r['tempo']:.1f}  beats {len(r['beats'])}  hits {len(r['hits'])}  → {a.out}")


def cmd_looks(a):
    import numpy as np, cv2
    from .dots import Clip, frame, save
    from .looks import LOOKS
    from dataclasses import replace
    clip = Clip(a.src)
    fi = a.frame if a.frame is not None else clip.n // 2
    tiles = []
    for name, lk in LOOKS.items():
        if a.levels: lk = replace(lk, levels=1.0)
        im = cv2.resize(frame(clip, fi, lk), (480, 270), interpolation=cv2.INTER_AREA)
        cv2.putText(im, name, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
        cv2.putText(im, name, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
        tiles.append(im)
    while len(tiles) % 4: tiles.append(np.zeros_like(tiles[0]))
    sheet = np.concatenate([np.concatenate(tiles[i:i + 4], 1) for i in range(0, len(tiles), 4)], 0)
    out = a.out or os.path.join(a.src, 'looks.png')
    save(sheet, out)
    print('wrote', out)


def cmd_compare(a):
    from .edit import compare
    compare(a.original, a.processed, a.out)


def cmd_auto(a):
    from .prep import prep
    from .beats import analyze
    from .auto import plan, write_script, describe
    from .edit import has_audio
    video = os.path.abspath(a.video)
    name = os.path.splitext(os.path.basename(video))[0][:40]
    out = os.path.abspath(a.out or os.path.join('pieces', name))
    src = os.path.join(out, 'src')
    os.makedirs(out, exist_ok=True)
    # 1 预处理（同一个视频做过就跳过）
    meta_p = os.path.join(src, 'meta.json')
    if os.path.exists(meta_p) and json.load(open(meta_p)).get('source') == video and not a.reprep:
        meta = json.load(open(meta_p)); print(f'[1/4] 预处理已存在，跳过（{meta["frames"]} 帧）')
    else:
        print('[1/4] 预处理：帧 + 遮罩 + 深度')
        meta = prep(video, src, a.start, a.dur, a.mask, a.depth)
    # 2 节拍
    audio = os.path.abspath(a.audio) if a.audio else (video if has_audio(video) else None)
    beats_p = os.path.join(out, 'beats.json')
    if audio:
        print(f'[2/4] 测节拍：{os.path.basename(audio)}')
        b = analyze(audio)
    else:
        print('[2/4] 没有声音：用 120 BPM 的假节拍')
        D = meta['frames'] / 24
        bt = [i * 0.5 for i in range(int(D / 0.5) + 1)]
        b = dict(tempo=120.0, duration=D, beats=bt, halves=[i * 0.25 for i in range(int(D / 0.25) + 1)], hits=[], hit_strength=[])
    json.dump(b, open(beats_p, 'w'), indent=1)
    sync = (audio is None) or (audio == video)
    D = a.length or (min(b['duration'], meta['frames'] / 24) if sync else b['duration'])
    if D < 4:
        sys.exit(f'片长只有 {D:.1f} 秒，至少要 4 秒（--length 可以手动指定）')
    # 3 剪辑脚本
    pl = plan(meta, b, D, sync=sync, style=a.style)
    script = os.path.join(out, 'edit.py')
    if os.path.exists(script) and not a.overwrite:
        print(f'[3/4] {script} 已存在，不覆盖（要重新生成加 --overwrite）')
    else:
        write_script(script, src, beats_p, audio, pl)
        print(f'[3/4] 生成剪辑脚本 {script}')
    print(describe(pl))
    if a.plan_only:
        return
    # 4 渲染（用当前解释器跑脚本，脚本里 import dotkit）
    print('[4/4] 渲染')
    env = dict(os.environ)
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env['PYTHONPATH'] = pkg_root + os.pathsep + env.get('PYTHONPATH', '')
    cmd = [sys.executable, script] + (['--workers', str(a.workers)] if a.workers else [])
    subprocess.run(cmd, check=True, env=env)
    mp4 = os.path.join(out, 'dots.mp4')
    if a.compare:
        from .edit import compare
        compare(video, mp4, os.path.join(out, 'compare.mp4'))
    print(f'\n完成：{mp4}' + (f'\n对照：{os.path.join(out, "compare.mp4")}' if a.compare else ''))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='dotkit', description='把人物视频做成按节拍切换的点阵风（点之战）')
    sp = ap.add_subparsers(dest='cmd', required=True)

    p = sp.add_parser('doctor', help='检查环境'); p.set_defaults(fn=cmd_doctor)

    def prep_args(p):
        p.add_argument('--start', type=float, default=0, help='从素材第几秒开始')
        p.add_argument('--dur', type=float, default=0, help='只取多少秒（0 = 全部）')
        p.add_argument('--mask', choices=['model', 'key'], default='model', help='model=人物分割模型；key=纯色背景抠像（快，不下模型）')
        p.add_argument('--depth', choices=['model', 'flat'], default='model', help='flat=不估深度（不能转机位）')

    p = sp.add_parser('auto', help='一条命令出片')
    p.add_argument('video')
    p.add_argument('--audio', help='配乐（不给就用视频自带的声音，画面和声音同步）')
    p.add_argument('--out', help='输出目录（默认 pieces/<视频名>）')
    p.add_argument('--length', type=float, help='成片秒数（默认 = 声音长度，和视频取短）')
    p.add_argument('--style', choices=['auto', 'dark', 'color'], default='auto', help='dark=暗素材模式（拉色阶 + 双色）')
    p.add_argument('--plan-only', action='store_true', help='只生成剪辑脚本，不渲染')
    p.add_argument('--overwrite', action='store_true', help='覆盖已有的 edit.py')
    p.add_argument('--reprep', action='store_true', help='强制重新预处理')
    p.add_argument('--no-compare', dest='compare', action='store_false', help='不出上下对照版')
    p.add_argument('--workers', type=int)
    prep_args(p); p.set_defaults(fn=cmd_auto)

    p = sp.add_parser('prep', help='预处理：帧 + 遮罩 + 深度'); p.add_argument('video'); p.add_argument('out')
    prep_args(p); p.set_defaults(fn=cmd_prep)

    p = sp.add_parser('beats', help='测节拍'); p.add_argument('audio'); p.add_argument('out'); p.set_defaults(fn=cmd_beats)

    p = sp.add_parser('looks', help='所有 look 的对照图'); p.add_argument('src')
    p.add_argument('--frame', type=int); p.add_argument('--out'); p.add_argument('--levels', action='store_true')
    p.set_defaults(fn=cmd_looks)

    p = sp.add_parser('compare', help='上原画下点阵'); p.add_argument('original'); p.add_argument('processed'); p.add_argument('out')
    p.set_defaults(fn=cmd_compare)

    a = ap.parse_args(argv)
    r = a.fn(a)
    sys.exit(r or 0)


if __name__ == '__main__':
    main()
