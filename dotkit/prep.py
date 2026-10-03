"""素材预处理：视频 → 1080p 帧 + 每帧的人物遮罩和深度（点阵渲染的原料）。

输出目录结构：
  rgb/00000.jpg   1920x1080 原画（原画段、色散闪帧用）
  aux/00000.npz   rgb(270x480x3 u8)、mask(270x480 u8 0-255)、depth(270x480 f16, 1=近 0=远)
  meta.json       帧数、fps、镜头切点、每帧的人物面积和运动量（自动导演要用）

遮罩：
  model  Mask2Former 人物实例 ∪ 人物附近的深度前景（补刀、披风、头发）。默认。
  key    背景色抠像：取画面四边的中位色当背景。纯色背景的素材用它，快，不用下模型。
深度：
  model  Depth Anything V2 Small，整段统一归一化（逐帧归一化会让点云前后跳）。默认。
  flat   不估深度（全部 0.5）。只做平面点阵、不转机位时可以用。
"""
import json, os, shutil, subprocess
import numpy as np
from PIL import Image
from scipy import ndimage

W, H = 480, 270          # 采样分辨率：最细的点阵一行 160 个点，480 够每个点 3 个采样
OUT_W, OUT_H = 1920, 1080
MASK_MODEL = 'facebook/mask2former-swin-small-coco-instance'
DEPTH_MODEL = 'depth-anything/Depth-Anything-V2-Small-hf'


def device():
    import torch
    if torch.cuda.is_available(): return 'cuda'
    if torch.backends.mps.is_available(): return 'mps'
    return 'cpu'


def extract(video, out, start=0.0, dur=0.0, fps=24):
    if os.path.isdir(f'{out}/rgb'): shutil.rmtree(f'{out}/rgb')
    os.makedirs(f'{out}/rgb')
    cmd = ['ffmpeg', '-v', 'error', '-y']
    if start: cmd += ['-ss', str(start)]
    cmd += ['-i', video]
    if dur: cmd += ['-t', str(dur)]
    cmd += ['-vf', f'fps={fps},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}',
            '-q:v', '2', '-start_number', '0', f'{out}/rgb/%05d.jpg']
    subprocess.run(cmd, check=True)
    return len(os.listdir(f'{out}/rgb'))


class _Models:
    def __init__(self, mask_mode, depth_mode):
        self.dev = device()
        self.depth_pipe = self.seg = None
        if depth_mode == 'model':
            from transformers import pipeline
            self.depth_pipe = pipeline('depth-estimation', model=DEPTH_MODEL, device=self.dev)
        if mask_mode == 'model':
            from transformers import AutoImageProcessor, Mask2FormerForUniversalSegmentation
            self.seg_proc = AutoImageProcessor.from_pretrained(MASK_MODEL)
            self.seg = Mask2FormerForUniversalSegmentation.from_pretrained(MASK_MODEL).to(self.dev).eval()

    def depth(self, img):
        import torch
        d = self.depth_pipe(img.resize((960, 540), Image.BILINEAR))['predicted_depth']
        d = d[None, None] if d.dim() == 2 else d[None]
        return torch.nn.functional.interpolate(d, size=(H, W), mode='bilinear', align_corners=False)[0, 0].cpu().numpy()

    def person(self, img):
        import torch
        with torch.no_grad():
            inp = self.seg_proc(images=img.resize((960, 540)), return_tensors='pt').to(self.dev)
            o = self.seg(**inp)
        r = self.seg_proc.post_process_instance_segmentation(o, target_sizes=[(H, W)], threshold=0.5)[0]
        m = np.zeros((H, W), bool)
        seg_map = r['segmentation'].cpu().numpy()
        for info in r['segments_info']:
            if info['label_id'] == 0:              # COCO 0 = person
                m |= seg_map == info['id']
        return m


def key_mask(small, thr=40.0):
    """背景色抠像：画面四边的中位色 = 背景。"""
    s = small.astype(np.float32)
    border = np.concatenate([s[0], s[-1], s[:, 0], s[:, -1]])
    bg = np.median(border, 0)
    dist = np.linalg.norm(s - bg, axis=2)
    m = dist > thr
    m = ndimage.binary_opening(m, iterations=1)
    lab, n = ndimage.label(m)                       # 去掉小碎块
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        m = np.isin(lab, 1 + np.nonzero(sizes >= max(30, sizes.max() * 0.02))[0])
    return m


def prep(video, out, start=0.0, dur=0.0, mask='model', depth='model', fg_depth=0.35, log=print):
    os.makedirs(out, exist_ok=True)
    n = extract(video, out, start, dur)
    if n == 0: raise RuntimeError(f'没抽到帧：{video}')
    log(f'{n} frames, mask={mask}, depth={depth}')
    M = _Models(mask, depth)
    if M.dev == 'cpu' and 'model' in (mask, depth):
        log('  (没有 GPU / MPS，用 CPU 跑模型，会比较慢：约 3–6 秒一帧)')
    raw_depth, masks, smalls = [], [], []
    for i in range(n):
        img = Image.open(f'{out}/rgb/{i:05d}.jpg').convert('RGB')
        small = np.asarray(img.resize((W, H), Image.LANCZOS))
        if depth == 'model':
            d = M.depth(img)
        else:
            d = np.full((H, W), 0.5, np.float32)
        m = M.person(img) if mask == 'model' else key_mask(small)
        raw_depth.append(d); masks.append(m); smalls.append(small)
        if i % 24 == 0: log(f'  {i}/{n}')

    D = np.stack(raw_depth)
    if depth == 'model':
        lo, hi = float(np.percentile(D, 2)), float(np.percentile(D, 99.5))     # 整段统一归一化
    else:
        lo, hi = 0.0, 1.0
    os.makedirs(f'{out}/aux', exist_ok=True)
    area, motion, cuts = [], [], [0]
    prev = None
    for i in range(n):
        d = np.clip((D[i] - lo) / (hi - lo + 1e-6), 0, 1) if depth == 'model' else D[i]
        m = masks[i]
        if mask == 'model' and depth == 'model' and fg_depth > 0:
            bg = np.median(d[~m]) if (~m).any() else 0
            rows = np.nonzero(masks[i].any(1))[0]
            near = ndimage.binary_dilation(m, iterations=12)             # 只在人物附近补（刀、披风、头发）
            above = np.arange(H)[:, None] < (rows.max() - 4 if len(rows) else H)   # 脚底以下不补（地面）
            m = m | (near & above & (d > max(fg_depth, bg + 0.15)))
        m = ndimage.binary_opening(m, iterations=1)
        m = ndimage.binary_dilation(m, iterations=1)
        soft = ndimage.gaussian_filter(m.astype(np.float32), 0.8)
        np.savez_compressed(f'{out}/aux/{i:05d}.npz', rgb=smalls[i], mask=(soft * 255).astype(np.uint8),
                            depth=d.astype(np.float16))
        # 统计：人物面积、运动量、镜头切点
        g = smalls[i].astype(np.float32).mean(2)
        area.append(float(m.mean()))
        if prev is not None:
            diff = float(np.abs(g - prev).mean())
            motion.append(diff)
        else:
            motion.append(0.0)
        prev = g
    mo = np.array(motion)
    for i in range(1, n):                                             # 画面突变（比前后几帧的运动量大 3.5 倍）= 镜头切换
        nb = np.concatenate([mo[max(1, i - 6):i], mo[i + 1:i + 7]])
        if len(nb) >= 3 and mo[i] > max(25.0, 3.5 * np.median(nb)) and i - cuts[-1] > 6:
            cuts.append(i)
    meta = {'frames': n, 'fps': 24, 'w': W, 'h': H, 'depth_lo': lo, 'depth_hi': hi,
            'mask_mode': mask, 'depth_mode': depth, 'source': os.path.abspath(video),
            'cuts': cuts, 'area': [round(a, 4) for a in area], 'motion': [round(x, 2) for x in motion],
            'fg_luma_mean': float(np.mean([smalls[i][masks[i]].mean() if masks[i].any() else 0 for i in range(0, n, max(1, n // 24))])) / 255,
            'fg_luma_std': float(np.mean([smalls[i][masks[i]].std() if masks[i].any() else 0 for i in range(0, n, max(1, n // 24))])) / 255}
    json.dump(meta, open(f'{out}/meta.json', 'w'), indent=1)
    log(f'done {out}  (镜头切点 {cuts}，人物平均亮度 {meta["fg_luma_mean"]:.2f})')
    return meta
