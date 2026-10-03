"""从参考片《点之战》里量出来的 look 预设。每半拍换一个。

颜色都是从参考片截帧里吸的；点距是 1920 宽下的像素。
"""
from .dots import Look

LOOKS = {
    # —— 纸色 / 纯色底 + 单色半调（暗处点大，亮处点消失）——
    'cream_navy':   Look(bg='#F2EADB', color='mono', c1='#1D2341', size_by='dark', spacing=13, size=0.56, min_r=1.0),
    'blue_white':   Look(bg='#2B2DF2', color='mono', c1='#FFFFFF', size_by='bright', spacing=13, size=0.56, min_r=1.0),
    'yellow_black': Look(bg='#F6E61C', color='mono', c1='#141414', size_by='dark', spacing=13, size=0.56, min_r=1.0),
    'cyan_black':   Look(bg='#12F0EE', color='mono', c1='#111418', size_by='dark', spacing=12, size=0.56, min_r=1.0),
    'orange_black': Look(bg='#EE5A2A', color='mono', c1='#1A1414', size_by='dark', spacing=12, size=0.56, min_r=1.0),
    'magenta_white': Look(bg='#E8195A', color='mono', c1='#FFFFFF', size_by='bright', spacing=12, size=0.56, min_r=1.0),
    'white_navy':   Look(bg='#F7F7F7', color='mono', c1='#26304E', size_by='dark', spacing=10, size=0.56, min_r=0.8),
    # —— 黑底剪影：整块一个颜色，点大小一样 ——
    'black_pink':   Look(bg='#060606', color='mono', c1='#E9787B', spacing=10, size=0.46),
    'black_salmon': Look(bg='#0A0606', color='duo', c1='#C8504E', c2='#F6B0A0', spacing=9, size=0.48),
    # —— 原色点 ——
    'orig_dense':   Look(bg='#000000', color='orig', spacing=7, size=0.5, sat=1.25),
    'orig_mid':     Look(bg='#000000', color='orig', spacing=12, size=0.46, sat=1.25),
    'orig_field':   Look(bg='#000000', color='orig', spacing=22, size=0.46, fg_only=False, bg_dot='#C9422F', bg_size=0.24, sat=1.3),
    'orig_coarse':  Look(bg='#000000', color='orig', spacing=64, size=0.47, fg_only=False, bg_dot='#C2402E', bg_size=0.3, sat=1.3),
    'glimpse':      Look(bg='#000000', color='orig', spacing=40, size=0.47, fg_only=False, bg_size=0.47, sat=1.15),
    'red_full':     Look(bg='#160604', color='orig', spacing=9, size=0.5, fg_only=False, sat=1.5, gain=0.95),
    'square_full':  Look(bg='#120604', color='orig', spacing=56, size=0.5, shape='square', fg_only=False, sat=1.4),
    # —— 发光散点（深色底 + 一个亮色 + 辉光，点大小随机）——
    'gold_glow':    Look(bg='#0D0C22', color='mono', c1='#FFD58C', layout='scatter', jitter=0.6, spacing=12,
                         size=0.42, size_var=0.75, density=0.55, glow=1.1),
    'purple_glow':  Look(bg='#0E0720', color='mono', c1='#EBA6F5', layout='scatter', jitter=0.6, spacing=12,
                         size=0.42, size_var=0.75, density=0.55, glow=1.2),
    'white_sparse': Look(bg='#030303', color='mono', c1='#FFFFFF', layout='scatter', jitter=0.7, spacing=15,
                         size=0.45, size_var=0.8, density=0.45, glow=0.35),
    'white_bokeh':  Look(bg='#020202', color='mono', c1='#FFFFFF', layout='scatter', jitter=0.8, spacing=30,
                         size=0.5, size_var=1.0, density=0.5, glow=0.4),
    # —— 墨团（点放大粘连）——
    'orange_blob':  Look(bg='#F28A3C', color='mono', c1='#151313', layout='scatter', jitter=0.4, spacing=40,
                         size=0.62, size_var=0.55, density=0.9, soft=3.0),   # 配 ca=5 色散
}

# 半拍轮换的默认顺序（参考片 3–9 秒那段的顺序，大致是 亮底 / 黑底 / 发光 交替）
CYCLE = ['cream_navy', 'black_pink', 'gold_glow', 'black_salmon', 'yellow_black', 'orig_dense',
         'white_sparse', 'orig_mid', 'red_full', 'white_bokeh', 'gold_glow', 'purple_glow',
         'blue_white', 'orange_blob', 'orange_black', 'cyan_black', 'square_full', 'magenta_white']

# 彩色残影的颜色（参考片 13–16 秒）
TRAIL = ['#FF5FA8', '#FFB23F', '#8A6CFF', '#3FD7FF', '#FF7A3F', '#B8FF6A']
