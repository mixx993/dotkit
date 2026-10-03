"""剪辑层：在节拍网格上排镜头，逐帧算出 (源帧, look, 机位, 特效)，多进程渲染，配声音出片。

    from dotkit import Edit, Cam, LOOKS
    E = Edit('pieces/x/beats.json', dur=20)
    E.shot(0, 1.25, 'src/a', src=0, speed=0.5, look='orig_dense', raw=1)            # 原画
    E.shot(3.2, 9.7, 'src/a', looks=CYCLE, switch='halves')                       # 每半拍换 look
    E.shot(9.7, 12, 'src/a', src=8, speed=0, look='orig_dense',
           anim={'yaw': (0, 40, 'inout'), 'extrude': 160})                        # 时间停止 + 环绕
    E.hit(10.63, 'flash'); E.hits_from_audio(kinds=('squash', 'ca'))
    E.run('pieces/x', audio='music.mp3', name='out')      # 渲染 + 配声音；命令行可加 --frames 120 180 只渲染一段

规则：后加的镜头盖住先加的（1 帧的「闪现」镜头直接后加就行）。
anim 的键：Cam 字段直接写（yaw / explode / zoom / pan ...），Look 字段加前缀 'look.'（look.spacing / look.size ...）；
值是常数，或 (起, 止[, 缓动])，缓动 in / out / inout / lin / expo_out。
"""
import json, os, subprocess, sys
from dataclasses import replace, fields
from multiprocessing import Pool
import numpy as np

from .dots import Look, Cam, Clip, frame, save
from .looks import LOOKS


def ease(u, kind='inout'):
    u = float(np.clip(u, 0, 1))
    if kind == 'in': return u ** 3
    if kind == 'out': return 1 - (1 - u) ** 3
    if kind == 'expo_out': return 1 - 2 ** (-10 * u) if u < 1 else 1.0
    if kind == 'lin': return u
    return 3 * u * u - 2 * u ** 3


CAM_KEYS = {f.name for f in fields(Cam)}
LOOK_KEYS = {f.name for f in fields(Look)}


def _val(v, u):
    if isinstance(v, tuple) and len(v) in (2, 3) and not isinstance(v[0], tuple):
        a, b = v[0], v[1]
        k = ease(u, v[2] if len(v) == 3 else 'inout')
        return a + (b - a) * k
    if isinstance(v, tuple) and len(v) in (2, 3) and isinstance(v[0], tuple):   # 元组参数（pan / squash）
        a, b = v[0], v[1]
        k = ease(u, v[2] if len(v) == 3 else 'inout')
        return tuple(x + (y - x) * k for x, y in zip(a, b))
    return v


class Edit:
    def __init__(self, beats=None, dur=None, fps=24):
        self.fps = fps
        self.b = json.load(open(beats)) if isinstance(beats, str) else (beats or {})
        self.dur = dur or self.b.get('duration', 10)
        self.n = int(round(self.dur * fps))
        self.shots, self.hits = [], []
        self._nclip = {}

    # —— 节拍工具 ——
    def halves(self, t0=0, t1=1e9):
        return [h for h in self.b.get('halves', []) if t0 <= h < t1]

    def beats(self, t0=0, t1=1e9):
        return [h for h in self.b.get('beats', []) if t0 <= h < t1]

    def snap(self, t):
        hs = self.b.get('halves') or [t]
        return min(hs, key=lambda h: abs(h - t))

    # —— 镜头 ——
    def shot(self, t0, t1, clip, src=0, speed=1.0, look='orig_dense', looks=None, switch='halves',
             cam=None, anim=None, trail=None, raw=0.0, ca=0.0, flash=0.0, pingpong=True, shutter=1):
        self.shots.append(dict(t0=t0, t1=t1, clip=clip, src=src, speed=speed, look=look, looks=looks,
                               switch=switch, cam=cam or Cam(), anim=anim or {}, trail=trail, raw=raw,
                               ca=ca, flash=flash, pingpong=pingpong, shutter=shutter))
        return self

    def hit(self, t, kind='squash', strength=1.0):
        """kind: squash（点被压扁 3 帧）| flash（白闪 1 帧）| ca（色散 4 帧衰减）| pop（点放大 3 帧）| burst（炸成白色发光大点 3 帧）"""
        self.hits.append((t, kind, strength))
        return self

    def hits_from_audio(self, kinds=('squash', 'ca'), t0=0, t1=1e9, min_strength=0.35):
        for t, s in zip(self.b.get('hits', []), self.b.get('hit_strength', [])):
            if t0 <= t < t1 and s >= min_strength:
                for k in kinds: self.hit(t, k, s)
        return self

    # —— 逐帧解析 ——
    def _src_index(self, s, T, nclip):
        if s['speed'] == 0: return int(s['src'])
        f = s['src'] + s['speed'] * (T - s['t0']) * self.fps
        if not s['pingpong']: return int(np.clip(f, 0, nclip - 1))
        p = 2 * (nclip - 1)
        f = f % p
        return int(f if f < nclip else p - f)

    def spec(self, fi, sub=0.0):
        T = (fi + sub) / self.fps
        s = None
        for sh in self.shots:
            if sh['t0'] <= T < sh['t1']: s = sh
        if s is None: return None
        u = (T - s['t0']) / max(s['t1'] - s['t0'], 1e-6)
        # look：固定一个，或在节拍上轮换
        look = s['look']
        if s['looks']:
            marks = self.halves(s['t0'], s['t1']) if s['switch'] == 'halves' else \
                self.beats(s['t0'], s['t1']) if s['switch'] == 'beats' else \
                list(np.arange(s['t0'], s['t1'], float(s['switch'])))
            k = sum(1 for m in marks if m <= T + 1e-6)
            look = s['looks'][k % len(s['looks'])]
        look = LOOKS[look] if isinstance(look, str) else look
        cam = s['cam']
        lk_over, cam_over = {}, {}
        for key, v in s['anim'].items():
            val = _val(v, u)
            if key.startswith('look.'): lk_over[key[5:]] = val
            else: cam_over[key] = val
        look = replace(look, **lk_over) if lk_over else look
        cam = replace(cam, **cam_over) if cam_over else cam
        flash, ca = s['flash'], s['ca']
        # 打击事件
        sq = 1.0
        for t, kind, st in self.hits:
            df = fi - int(round(t * self.fps))
            if kind == 'flash' and df == 0: flash = max(flash, 0.85 * st)
            if kind == 'ca' and 0 <= df < 4: ca = max(ca, 14 * st * (1 - df / 4))
            if kind == 'squash' and 0 <= df < 3:
                sq = min(sq, 1 - 0.55 * st * (1 - df / 3))
            if kind == 'burst' and 0 <= df < 3:          # 打击瞬间人物炸成发白光的大点
                look = replace(look, color='mono', c1='#FFFFFF', size=look.size * (1.6 - 0.2 * df),
                               size_var=0.8, density=0.55, glow=max(look.glow, 0.8), min_r=0)
            if kind == 'pop' and 0 <= df < 3:
                look = replace(look, size=look.size * (1 + 0.6 * st * (1 - df / 3)))
        if sq < 1:
            cam = replace(cam, squash=(cam.squash[0] * (2 - sq) ** 0.6, cam.squash[1] * sq))
        if s['clip'] not in self._nclip:
            self._nclip[s['clip']] = json.load(open(f"{s['clip']}/meta.json"))['frames']
        clip_n = self._nclip[s['clip']]
        out = dict(clip=s['clip'], src=self._src_index(s, T, clip_n), look=look, cam=cam,
                   trail=s['trail'], raw=s['raw'], ca=ca, flash=flash)
        if sub == 0 and s['shutter'] > 1:        # 运动模糊：半个快门里再采几帧，平均
            n = s['shutter']
            out['subs'] = [self.spec(fi, 0.5 * k / n) for k in range(1, n)]
        return out

    # —— 渲染 ——
    def render(self, out_dir, workers=None, frames=None, log=print):
        os.makedirs(out_dir, exist_ok=True)
        workers = workers or max(1, (os.cpu_count() or 4) - 2)
        jobs = [(fi, self.spec(fi), f'{out_dir}/{fi:05d}.png') for fi in (frames or range(self.n))]
        with Pool(workers) as p:
            for k, _ in enumerate(p.imap_unordered(_work, jobs, chunksize=2)):
                if k % 48 == 0: log(f'  {k}/{len(jobs)}')
        log(f'rendered {len(jobs)} frames → {out_dir}')

    def mux(self, frames_dir, audio, out, crf=16):
        cmd = ['ffmpeg', '-v', 'error', '-y', '-framerate', str(self.fps), '-i', f'{frames_dir}/%05d.png']
        if audio and has_audio(audio):
            cmd += ['-i', audio, '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '256k', '-shortest']
        cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', str(crf), '-preset', 'slow', out]
        subprocess.run(cmd, check=True)
        print('wrote', out)

    def run(self, piece_dir, audio=None, name='out', argv=None):
        """剪辑脚本的入口：python edit.py [--frames A B] [--workers N]"""
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument('--frames', nargs=2, type=int, help='只渲染这一段帧（调参用，不出 mp4）')
        ap.add_argument('--workers', type=int)
        a = ap.parse_args(argv if argv is not None else sys.argv[1:])
        out = f'{piece_dir}/frames'
        if a.frames:
            self.render(out, a.workers, range(*a.frames))
            return None
        self.render(out, a.workers)
        mp4 = f'{piece_dir}/{name}.mp4'
        self.mux(out, audio, mp4)
        return mp4


def has_audio(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def compare(original, processed, out, label_top='original', label_bottom='dots', width=1280):
    """上原画、下点阵的同屏对照（声音用处理后那条）。"""
    h = width * 9 // 16
    font = next((f for f in ['/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Helvetica.ttc',
                             '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf']
                 if os.path.exists(f)), None)

    def lab(t):
        if not font: return ''
        f = font.replace('\\', '/').replace(':', '\\:')
        return f",drawtext=fontfile='{f}':text='{t}':x=16:y=12:fontsize={width // 46}:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=6"
    fc = (f"[0:v]fps=24,scale={width}:{h}:force_original_aspect_ratio=increase,crop={width}:{h},setsar=1{lab(label_top)}[a];"
          f"[1:v]fps=24,scale={width}:{h},setsar=1{lab(label_bottom)}[b];[a][b]vstack=shortest=1[v]")
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', original, '-i', processed, '-filter_complex', fc, '-map', '[v]']
    if has_audio(processed): cmd += ['-map', '1:a', '-c:a', 'aac', '-b:a', '192k']
    cmd += ['-c:v', 'libx264', '-b:v', '12M', '-maxrate', '14M', '-bufsize', '20M', '-pix_fmt', 'yuv420p', '-shortest', out]
    subprocess.run(cmd, check=True)
    print('wrote', out)


_CLIPS = {}


def _work(job):
    fi, sp, path = job
    if sp is None:
        save(np.zeros((1080, 1920, 3), np.uint8), path); return fi
    acc = None
    for q in [sp] + sp.get('subs', []):
        c = _CLIPS.get(q['clip']) or _CLIPS.setdefault(q['clip'], Clip(q['clip']))
        img = frame(c, q['src'], q['look'], q['cam'], trail=q['trail'], flash=q['flash'], ca=q['ca'], raw=q['raw'])
        acc = img.astype(np.float32) if acc is None else acc + img
    save((acc / (1 + len(sp.get('subs', [])))).astype(np.uint8), path)
    return fi
