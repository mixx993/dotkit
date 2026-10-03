"""点阵渲染核心：一帧素材（颜色 + 遮罩 + 深度）+ 一个 look + 一个机位 → 一张 1920x1080。

每个点都是真三维的：按深度反投影成点云（默认机位下正好落回原位置），所以同一套数据可以
  · 平面看（2D 点阵 / 半调）
  · 绕着转（时间停止 + 环绕）
  · 炸向镜头（点越近越大越虚 = 焦外光斑）

画点用 cv2 抗锯齿亚像素椭圆，图层是预乘 alpha，景深按模糊量分桶后分层模糊再叠。
"""
import os, json
from dataclasses import dataclass, field, replace
import numpy as np
import cv2

OW, OH = 1920, 1080
SHIFT = 4                      # cv2 亚像素：坐标乘 16
F_PX = OW / (2 * np.tan(np.radians(40) / 2))   # 40° 水平视角的焦距（像素）
Z0 = F_PX                      # 画面平面放在 z=F：默认机位下 1 像素 = 1 世界单位


def hexc(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


# ---------------------------------------------------------------- 素材
class Clip:
    def __init__(self, root):
        self.root = root
        self.meta = json.load(open(f'{root}/meta.json'))
        self.n = self.meta['frames']
        self._aux, self._rgb = {}, {}

    def aux(self, i):
        i = int(np.clip(i, 0, self.n - 1))
        if i not in self._aux:
            z = np.load(f'{self.root}/aux/{i:05d}.npz')
            self._aux[i] = (z['rgb'].astype(np.float32), z['mask'].astype(np.float32) / 255,
                            z['depth'].astype(np.float32))
            if len(self._aux) > 64: self._aux.pop(next(iter(self._aux)))
        return self._aux[i]

    def rgb(self, i):
        i = int(np.clip(i, 0, self.n - 1))
        if i not in self._rgb:
            self._rgb[i] = cv2.cvtColor(cv2.imread(f'{self.root}/rgb/{i:05d}.jpg'), cv2.COLOR_BGR2RGB)
            if len(self._rgb) > 16: self._rgb.pop(next(iter(self._rgb)))
        return self._rgb[i]


# ---------------------------------------------------------------- 风格参数
@dataclass
class Look:
    bg: str = '#000000'
    spacing: float = 16          # 点距（输出像素，机位缩放之前）
    layout: str = 'grid'         # grid | hex | scatter
    jitter: float = 0.0          # scatter 抖动（相对点距）
    size: float = 0.42           # 半径 / 点距（0.5 = 相切）
    size_by: str = 'const'       # const | dark（半调：暗处点大）| bright | random | depth
    size_var: float = 0.0        # 随机大小变化（0..1），焦外光斑感
    color: str = 'orig'          # orig | mono | duo
    c1: str = '#ffffff'          # mono 色 / duo 暗部色
    c2: str = '#ffffff'          # duo 亮部色
    sat: float = 1.15            # orig 的饱和度
    gain: float = 1.0            # 点颜色亮度
    fg_only: bool = True         # 只画人物；False 则背景格子也画
    bg_dot: str = ''             # 背景格子颜色（'' 用原色）
    bg_size: float = 0.25        # 背景格子的半径 / 点距
    density: float = 1.0         # 保留点的比例（稀疏的发光点 0.3–0.6）
    min_r: float = 0.0           # 半径小于这个像素就不画（半调里亮处直接消失）
    shape: str = 'circle'        # circle | square
    glow: float = 0.0            # 辉光强度（发光点 0.8–1.5）
    blob: float = 0.0            # 融合成墨团（0 关；0.6 左右开始粘连）
    alpha: float = 1.0
    soft: float = 0.0            # 点图层整体模糊（像素），墨团 / 失焦感
    levels: float = 0.0          # 遮罩内自动拉色阶（0 关，1 拉满）：素材又暗又灰（黑衣服、灰背景）时开


@dataclass
class Cam:
    yaw: float = 0.0             # 度，绕人物中心
    pitch: float = 0.0
    roll: float = 0.0
    zoom: float = 1.0            # 焦距倍数（推镜头）
    dolly: float = 0.0           # 机位往前推（世界单位，>0 靠近）
    pan: tuple = (0.0, 0.0)      # 画面平移（像素）
    depth: float = 900.0         # 深度尺度：depth 0→1 对应多少世界单位
    pivot: tuple = (0.5, 0.5)    # 旋转中心（画面比例坐标）
    explode: float = 0.0         # 点炸开的距离（世界单位，朝镜头和四周）
    explode_seed: int = 7
    squash: tuple = (1.0, 1.0)   # 打击时点被压扁（sx, sy）
    dof: float = 0.0             # 景深强度（0 关）
    focus: float = 0.0           # 对焦距离偏移（0 = 对在人物上）
    extrude: float = 0.0         # 每个点往后挤出的厚度（世界单位）——转机位时人物才像实心的
    extrude_n: int = 4


# ---------------------------------------------------------------- 采样
def sample_points(clip, fi, look: Look, seed=0):
    """在源画面空间里布点，返回每个点的 屏幕 x,y（默认机位）、颜色、亮度、遮罩、深度、随机数。"""
    rgb, mask, depth = clip.aux(fi)
    h, w = mask.shape
    s = max(look.spacing, 3.0)
    cols, rows = max(int(round(OW / s)), 2), max(int(round(OH / s)), 2)
    sx, sy = OW / cols, OH / rows
    # 每格的平均颜色 / 遮罩 / 深度（INTER_AREA = 区域平均）
    c = cv2.resize(rgb, (cols, rows), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    m = cv2.resize(mask, (cols, rows), interpolation=cv2.INTER_AREA).reshape(-1)
    # 深度取遮罩内加权，避免轮廓上的点被背景深度拉远
    dm = cv2.resize(depth * mask, (cols, rows), interpolation=cv2.INTER_AREA).reshape(-1)
    d = np.where(m > 0.05, dm / np.maximum(m, 1e-3),
                 cv2.resize(depth, (cols, rows), interpolation=cv2.INTER_AREA).reshape(-1))
    gy, gx = np.mgrid[0:rows, 0:cols]
    x = (gx.reshape(-1) + 0.5) * sx
    y = (gy.reshape(-1) + 0.5) * sy
    if look.layout == 'hex':
        x = x + np.where(gy.reshape(-1) % 2 == 1, sx / 2, 0)
    rng = np.random.default_rng(seed + cols * 1000 + rows)
    rnd = rng.random((len(x), 4)).astype(np.float32)        # 每个点固定的随机数（同点距下帧间稳定）
    if look.layout == 'scatter' or look.jitter > 0:
        j = look.jitter if look.jitter > 0 else 0.5
        x = x + (rnd[:, 0] - 0.5) * 2 * j * sx
        y = y + (rnd[:, 1] - 0.5) * 2 * j * sy
    luma = (c @ np.array([0.299, 0.587, 0.114], np.float32)) / 255
    return dict(x=x, y=y, c=c, l=luma, m=m, d=d, r=rnd, s=min(sx, sy))


def shade(P, look: Look):
    """决定每个点的颜色和半径（世界单位 = 默认机位下的像素）。"""
    c, l, m, rnd, s = P['c'], P['l'], P['m'], P['r'], P['s']
    fg = m > 0.5
    if look.levels > 0 and fg.sum() > 20:
        lo, hi = np.percentile(l[fg], 3), np.percentile(l[fg], 97)
        ln = np.clip((l - lo) / max(hi - lo, 0.05), 0, 1)
        clo, chi = np.percentile(c[fg], 2, axis=0), np.percentile(c[fg], 98, axis=0)
        cn = np.clip((c - clo.min()) / max(chi.max() - clo.min(), 12) * 255, 0, 255)
        l = l + (ln - l) * look.levels
        c = c + (cn - c) * look.levels
    keep = fg.copy() if look.fg_only else np.ones_like(fg)
    if look.density < 1:
        keep &= (rnd[:, 2] < look.density) | (~fg)
    # 半径
    if look.size_by == 'dark':
        k = np.clip(1.15 - l * 1.2, 0, 1) ** 0.8
    elif look.size_by == 'bright':
        k = np.clip(l * 1.3 - 0.05, 0, 1) ** 0.8
    elif look.size_by == 'random':
        k = 0.35 + rnd[:, 3] * 0.9
    elif look.size_by == 'depth':
        k = 0.4 + P['d'] * 0.8
    else:
        k = np.ones_like(l)
    if look.size_var > 0:
        k = k * (1 - look.size_var + look.size_var * 2.2 * rnd[:, 3] ** 2)
    rad = look.size * s * k
    # 颜色
    if look.color == 'mono':
        col = np.tile(hexc(look.c1), (len(l), 1))
    elif look.color == 'duo':
        t = np.clip((l - 0.15) / 0.7, 0, 1)[:, None]
        col = hexc(look.c1) * (1 - t) + hexc(look.c2) * t
    else:
        g = c.mean(1, keepdims=True)
        col = np.clip(g + (c - g) * look.sat, 0, 255)
    col = np.clip(col * look.gain, 0, 255)
    # 背景格子
    if not look.fg_only:
        bgm = ~fg
        rad = np.where(bgm, look.bg_size * s, rad)
        if look.bg_dot:
            col[bgm] = hexc(look.bg_dot)
    keep &= rad >= max(look.min_r, 0.4)
    return col, rad, keep


# ---------------------------------------------------------------- 三维
def _rot(yaw, pitch, roll):
    a, b, g = np.radians([yaw, pitch, roll])
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    Rz = np.array([[np.cos(g), -np.sin(g), 0], [np.sin(g), np.cos(g), 0], [0, 0, 1]])
    return (Rz @ Rx @ Ry).astype(np.float32)


def project(P, rad, cam: Cam):
    """点反投影成点云 → 机位变换 → 投影。返回屏幕 x, y, 半径, 相机深度, 景深模糊量。"""
    x, y, d = P['x'], P['y'], P['d']
    Z = Z0 + (0.5 - d) * cam.depth                   # depth 1 = 近
    X = (x - OW / 2) * Z / F_PX
    Y = (y - OH / 2) * Z / F_PX
    R = rad * Z / F_PX
    pts = np.stack([X, Y, Z], 1).astype(np.float32)
    if cam.explode:
        rng = np.random.default_rng(cam.explode_seed)
        v = rng.normal(size=pts.shape).astype(np.float32)
        v[:, 2] = -np.abs(v[:, 2]) * 2.2 - 0.6        # 主要朝镜头飞
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        sp = 0.4 + rng.random(len(pts)).astype(np.float32) ** 2 * 1.6
        pts = pts + v * sp[:, None] * cam.explode
    piv = np.array([(cam.pivot[0] - 0.5) * OW, (cam.pivot[1] - 0.5) * OH, Z0], np.float32)
    Rm = _rot(cam.yaw, cam.pitch, cam.roll)
    pc = (pts - piv) @ Rm.T + piv
    pc[:, 2] -= cam.dolly
    zc = pc[:, 2]
    f = F_PX * cam.zoom
    ok = zc > 30
    zs = np.maximum(zc, 30)
    sx = pc[:, 0] * f / zs + OW / 2 + cam.pan[0]
    sy = pc[:, 1] * f / zs + OH / 2 + cam.pan[1]
    sr = R * f / zs
    zf = Z0 - cam.dolly + cam.focus
    blur = cam.dof * sr * np.abs(zs - zf) / zs if cam.dof else np.zeros_like(sr)
    return sx, sy, sr, zs, blur, ok


# ---------------------------------------------------------------- 画
def _draw(layer, xs, ys, rs, cols, alpha, look, squash):
    """预乘 alpha 图层上画点（cv2 抗锯齿，亚像素）。"""
    m = 1 << SHIFT
    a255 = int(255 * alpha)
    sqx, sqy = squash
    for x, y, r, c in zip(xs, ys, rs, cols):
        if r < 0.35: continue
        col = (float(c[0]) * alpha, float(c[1]) * alpha, float(c[2]) * alpha, a255)
        cx, cy = int(x * m), int(y * m)
        if look.shape == 'square':
            hx, hy = r * sqx * 0.9, r * sqy * 0.9
            pts = np.array([[x - hx, y - hy], [x + hx, y - hy], [x + hx, y + hy], [x - hx, y + hy]]) * m
            cv2.fillConvexPoly(layer, pts.astype(np.int32), col, cv2.LINE_AA, SHIFT)
        else:
            ax = (max(int(r * sqx * m), 1), max(int(r * sqy * m), 1))
            cv2.ellipse(layer, (cx, cy), ax, 0, 0, 360, col, -1, cv2.LINE_AA, SHIFT)


def render_points(P, look: Look, cam: Cam, alpha=1.0):
    """返回预乘 RGBA float32 图层（OH, OW, 4），0..255。"""
    col, rad, keep = shade(P, look)
    if cam.extrude and cam.extrude_n > 1:
        n = cam.extrude_n
        k = np.repeat(np.arange(n, dtype=np.float32), len(rad))
        P = {**P, 'x': np.tile(P['x'], n), 'y': np.tile(P['y'], n),
             'd': np.tile(P['d'], n) - k * (cam.extrude / n) / cam.depth}
        col = np.tile(col, (n, 1)) * (1 - 0.35 * k / n)[:, None]
        rad, keep = np.tile(rad, n), np.tile(keep, n)
    sx, sy, sr, zs, blur, ok = project(P, rad, cam)
    keep = keep & ok & (sx + sr > -50) & (sx - sr < OW + 50) & (sy + sr > -50) & (sy - sr < OH + 50)
    idx = np.nonzero(keep)[0]
    idx = idx[np.argsort(-zs[idx])]                  # 远的先画
    out = np.zeros((OH, OW, 4), np.float32)
    a = look.alpha * alpha
    if not cam.dof:
        _draw(out, sx[idx], sy[idx], sr[idx], col[idx], a, look, cam.squash)
        return out
    # 景深 = 圆盘焦外：模糊越大，盘越大、越透明；再按模糊量分桶给一点柔边。远 → 近 叠
    b = blur[idx]
    r2 = sr[idx] + b
    a_pt = np.clip((sr[idx] / np.maximum(r2, 1e-3)) ** 1.2, 0.28, 1.0)
    edges = [0, 3, 10, 30, 1e9]
    zf = Z0 - cam.dolly + cam.focus
    far = zs[idx] >= zf
    order = [(True, k) for k in range(len(edges) - 2, -1, -1)] + [(False, k) for k in range(len(edges) - 1)]
    for is_far, k in order:
        sel = (far == is_far) & (b >= edges[k]) & (b < edges[k + 1])
        if not sel.any(): continue
        L = np.zeros_like(out)
        for aa in np.unique(np.round(a_pt[sel], 1)):            # 透明度分几档画
            ss = np.round(a_pt[sel], 1) == aa
            _draw(L, sx[idx][sel][ss], sy[idx][sel][ss], r2[sel][ss], col[idx][sel][ss], a * aa, look, cam.squash)
        if k > 0:
            L = cv2.GaussianBlur(L, (0, 0), [0, 1.2, 3, 7][k])
        out = L + out * (1 - L[..., 3:4] / 255)
    return out


def comp_over(bg_rgb, layer):
    return layer[..., :3] + bg_rgb * (1 - layer[..., 3:4] / 255)


def bloom(img, amount, radii=(6, 24, 70)):
    if amount <= 0: return img
    acc = np.zeros_like(img)
    for r in radii:
        acc += cv2.GaussianBlur(img, (0, 0), r)
    return img + acc / len(radii) * amount


def blobify(layer, amount):
    """点融成墨团：模糊 alpha 后重新阈值。"""
    a = cv2.GaussianBlur(layer[..., 3], (0, 0), 6 + 10 * amount) / 255
    t = 0.5 - 0.25 * amount
    na = np.clip((a - t) / 0.06, 0, 1)
    col = layer[..., :3] / np.maximum(layer[..., 3:4] / 255, 1e-3)
    colb = cv2.GaussianBlur(col * (layer[..., 3:4] / 255), (0, 0), 8) / np.maximum(
        cv2.GaussianBlur(layer[..., 3:4] / 255, (0, 0), 8)[..., None], 1e-3)
    return np.concatenate([colb * na[..., None], na[..., None] * 255], -1).astype(np.float32)


def chroma(img, px):
    if px == 0: return img
    p = int(round(px))
    out = img.copy()
    out[..., 0] = np.roll(img[..., 0], p, axis=1)
    out[..., 2] = np.roll(img[..., 2], -p, axis=1)
    return out


def frame(clip, fi, look: Look, cam: Cam = None, *, trail=None, flash=0.0, ca=0.0,
          raw=0.0, extra=None):
    """一帧成片。
    trail: dict(n=5, step=2, colors=[...], look=Look) 彩色残影（过去的几帧，按颜色铺在后面）
    flash: 0..1 白闪；ca: 色散像素；raw: 0..1 混入原画；extra: 额外点图层列表（叠在最上）
    """
    cam = cam or Cam()
    bg = np.empty((OH, OW, 3), np.float32); bg[:] = hexc(look.bg)
    img = bg
    if trail:
        tl = trail.get('look') or look
        for k in range(trail['n'], 0, -1):
            Pk = sample_points(clip, max(fi - k * trail['step'], trail.get('floor', 0)), tl)
            lk = replace(tl, color='mono', c1=trail['colors'][(k - 1) % len(trail['colors'])], fg_only=True)
            sh = trail.get('shift', (0, 0))            # 素材动得少时，用平移把残影拉开
            ck = replace(cam, pan=(cam.pan[0] + k * sh[0], cam.pan[1] + k * sh[1]))
            L = render_points(Pk, lk, ck, alpha=trail.get('alpha', 0.85))
            img = comp_over(img, L)
    P = sample_points(clip, fi, look)
    L = render_points(P, look, cam)
    if look.blob:
        L = blobify(L, look.blob)
    if look.soft:
        L = cv2.GaussianBlur(L, (0, 0), look.soft)
    if look.glow:
        glow_src = L[..., :3].copy()
        img = comp_over(img, L)
        img = img + (bloom(glow_src, look.glow) - glow_src)
    else:
        img = comp_over(img, L)
    for E in extra or []:
        img = comp_over(img, E)
    if raw > 0:
        img = img * (1 - raw) + clip.rgb(fi).astype(np.float32) * raw
    if ca: img = chroma(img, ca)
    if flash > 0: img = img * (1 - flash) + 255 * flash
    return np.clip(img, 0, 255).astype(np.uint8)


def save(img, path):
    cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])
