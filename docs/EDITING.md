# 改剪辑脚本：edit.py 参考

`dotkit auto` 生成的 `edit.py` 是普通 Python，每一段画面是一行 `E.shot(...)`。改完运行：

```bash
python edit.py                      # 全片：渲染 + 配声音 → dots.mp4
python edit.py --frames 160 210     # 只渲染第 160–209 帧到 frames/，调参用（不出 mp4）
```

时间单位都是**秒**，帧率固定 24。

## E.shot —— 一段画面

```python
E.shot(t0, t1, SRC,
       src=0, speed=1.0, pingpong=True,       # 源帧：src + speed × (t - t0) × 24；speed=0 = 定格在 src 帧
       look='orig_dense',                     # 一个 look（名字或 Look 对象）
       looks=[...], switch='halves',          # 或者一组 look 轮换：'halves' 半拍 / 'beats' 每拍 / 0.25（秒）
       cam=Cam(...),                          # 机位（见下）
       anim={'yaw': (-30, 10, 'inout'),       # 关键帧：Cam 字段直接写；Look 字段加 'look.' 前缀
             'look.spacing': (90, 20, 'out')},#   值 = 常数 或 (起, 止[, 缓动])，缓动 in/out/inout/lin/expo_out
       trail=dict(n=4, step=1, colors=TRAIL, alpha=0.7, floor=0, shift=(0, 0)),   # 彩色残影
       raw=0.0,                               # 1 = 显示原画（原画段）
       ca=0.0, flash=0.0,                     # 整段的色散像素 / 白闪
       shutter=1)                             # >1 = 运动模糊（每帧采几个子帧）
```

- **后加的镜头盖住先加的。** 想在某处插 1 帧闪现，直接在后面加一个 1 帧长的 shot。
- 生成的脚本里有 `sync(t0, t1, **kw)`：源画面跟时间同步的快捷写法。

## E.hit —— 打击事件

```python
E.hit(6.85, 'flash')                               # squash / ca / flash / burst / pop，见 STYLE.md §4
E.hit(6.85, 'burst', 0.7)                          # 第三个参数是强度 0–1
E.hits_from_audio(kinds=('squash', 'ca'), t0=2, t1=9, min_strength=0.45)   # 用音频里测出的重拍
```

重拍时间在 `beats.json` 的 `hits` / `hit_strength` 里；拍点在 `beats`，半拍在 `halves`。

## Look —— 点怎么画（`dotkit/dots.py`）

```python
from dotkit import Look, LOOKS, replace
my = replace(LOOKS['cream_navy'], spacing=10, bg='#FFF4E0')     # 在预设上改
```

| 字段 | 含义 | 常用值 |
|---|---|---|
| `bg` | 背景色 | `'#000000'` |
| `spacing` | 点距（像素，1920 宽） | 7（密）– 64（粗） |
| `size` | 半径 / 点距（0.5 = 相切） | 0.42–0.56 |
| `size_by` | 点大小跟什么走 | `const` / `dark`（半调）/ `bright` / `random` / `depth` |
| `size_var` | 随机大小 | 0–1 |
| `color` | 颜色模式 | `orig`（原色）/ `mono`（`c1`）/ `duo`（暗 `c1` → 亮 `c2`） |
| `layout` / `jitter` | 排列 | `grid` / `hex` / `scatter` |
| `density` | 保留点的比例 | 发光散点 0.45–0.55 |
| `fg_only` / `bg_dot` / `bg_size` | 背景格子要不要画、什么颜色、多大 | |
| `glow` | 辉光 | 发光散点 0.8–1.3 |
| `shape` | `circle` / `square` | |
| `soft` / `blob` | 整体柔化 / 粘连成墨团 | |
| `levels` | 人物内自动拉色阶（暗素材开 1） | 0 / 1 |
| `min_r` | 小于这个半径的点不画（半调里亮处消失） | 0.8–1 |

## Cam —— 机位

| 字段 | 含义 | 常用值 |
|---|---|---|
| `yaw` / `pitch` / `roll` | 绕人物转（度） | 环绕 ±30 |
| `zoom` | 推近（焦距倍数） | 1–6 |
| `pan` | 画面平移（像素） | |
| `pivot` | 旋转中心（画面比例） | `(0.5, 0.55)` |
| `depth` | 深度尺度 | 1200–1500 |
| `extrude` / `extrude_n` | 点往后挤出的厚度 / 层数（环绕时用） | 110–150 / 6 |
| `explode` | 点炸开的距离（朝镜头和四周） | 炸向镜头 2600–4200 |
| `dof` / `focus` | 景深强度 / 对焦偏移 | 1.6–3 |
| `squash` | 点压扁 (sx, sy) | 一般用 `E.hit(..., 'squash')` |

## 典型改法

| 想要 | 改什么 |
|---|---|
| 换颜色 | 改 `looks=[...]` 列表，或 `replace(LOOKS[...], bg=..., c1=...)` |
| 切得更快 / 更慢 | `switch='halves'` ↔ `'beats'` |
| 定格换个时刻 | 改定格那两行的时间和 `src=`（源帧号 = 秒 × 24） |
| 炸得更猛 | `anim={'explode': (0, 4200, 'lin')}` 调大，`shutter` 调到 6 |
| 环绕幅度 | `anim={'yaw': (-32, 8)}` |
| 少一点白光 | 删掉 `E.hit(..., 'burst')` 或把 `hits_from_audio` 的 `min_strength` 调高 |
