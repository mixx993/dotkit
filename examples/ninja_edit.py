"""手调示例：《点之战 · 忍》——一段 15 秒双忍者对打（AI 生成，自带鼓点和刀剑声）。

比 `dotkit auto` 生成的脚本多了一些手工决定（定格选在双刀交叉那一帧、镜头切点的转场、只在两下最重的撞击上炸白光），
可以当作「自动出初版之后怎么精修」的参考。用法：
  1. dotkit prep 你的素材.mp4 pieces/ninja/src
  2. dotkit beats 你的素材.mp4 pieces/ninja/beats.json
  3. 把本文件复制到 pieces/ninja/edit.py，改 AUDIO 和各段时间
  4. python pieces/ninja/edit.py   （或 --frames 150 210 只渲染一段）


素材特点：一身黑 + 灰背景 → 所有 look 开 levels（遮罩内拉色阶），不然点是一片灰。
刀剑声和画面同步 → 除了定格那段，源画面跟着时间实时走（src = 镜头起点 × 24）。

"""
import os
from dotkit import Edit, Cam, Look, LOOKS, TRAIL, replace

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')
AUDIO = os.path.join(HERE, 'fight.mp4')          # 素材本身（用它的声音）
E = Edit(f'{HERE}/beats.json', dur=15.04)
F = 1 / 24
L = {k: replace(v, levels=1.0) for k, v in LOOKS.items()}
# 这条素材专用：钢蓝 → 暖白的双色（代替原色点，黑衣服原色太闷）
L['steel'] = Look(bg='#05060A', color='duo', c1='#26315C', c2='#F4E9D6', spacing=8, size=0.5, levels=1.0)
L['steel_mid'] = replace(L['steel'], spacing=12, size=0.46)
L['steel_field'] = Look(bg='#000000', color='duo', c1='#2A3566', c2='#F6E7D2', spacing=22, size=0.46, levels=1.0,
                        fg_only=False, bg_dot='#C9422F', bg_size=0.24)
L['steel_coarse'] = replace(L['steel_field'], spacing=64, bg_size=0.3)
L['ember'] = Look(bg='#030303', color='duo', c1='#C9422F', c2='#F6E7D2', spacing=8, size=0.5, levels=1.0)   # 结尾爆炸：红 → 米白


def sync(t0, t1, **kw):
    """源画面和时间同步的镜头。"""
    return E.shot(t0, t1, SRC, src=t0 * 24, speed=1, pingpong=False, **kw)


CYCLE = ['cream_navy', 'black_pink', 'gold_glow', 'steel', 'yellow_black', 'orig_dense',
         'white_sparse', 'blue_white', 'steel_mid', 'orange_black', 'purple_glow', 'cyan_black',
         'magenta_white', 'white_navy', 'orange_blob']
CYC = [L[k] for k in CYCLE]

# A 0–1.28  原画，单帧点阵闪现越来越密
sync(0, 1.28, look=L['steel'], raw=1)
for f in (6, 11, 15, 18, 21, 23, 25, 27, 29):
    E.shot(f * F, (f + 1) * F, SRC, src=f, speed=0, look=replace(L['glimpse'], levels=0.6))
# B 1.28 刀碰出火花 → 色散 2 帧
sync(1.28, 1.36, look=L['steel'], raw=1, ca=22)
# C 整个画面碎成点扑向镜头
E.shot(1.36, 1.83, SRC, src=33, speed=0, look=replace(L['glimpse'], spacing=9, size=0.5, levels=0.6),
       cam=Cam(dof=3.0), shutter=4, anim={'explode': (0, 2600, 'out')})
# D 从巨大的点里拉出来
sync(1.83, 2.53, look=L['steel_coarse'], cam=Cam(pivot=(0.5, 0.45)),
     anim={'zoom': (5.5, 1.0, 'out'), 'look.spacing': (90, 20, 'out')})
# E 每拍换 look，源画面实时；2.81 刀刃相撞炸白光
sync(2.53, 6.85, looks=CYC, switch='beats', anim={'zoom': (1.0, 1.08, 'lin')})
E.hits_from_audio(kinds=('squash', 'ca'), t0=2.0, t1=6.8, min_strength=0.45)
E.hit(2.81, 'burst').hit(4.64, 'burst', 0.7)
# F 6.85 双刀交叉 → 时间停止，绕着转（点云有厚度），每拍换 look
E.shot(6.85, 7.94, SRC, src=164, speed=0, looks=[L['steel'], L['black_pink'], L['orig_dense']], switch='beats',
       cam=Cam(depth=1200, extrude=110, extrude_n=6, pitch=5, pivot=(0.5, 0.55)), anim={'yaw': (-30, 8, 'inout')})
E.shot(7.94, 8.61, SRC, src=164, speed=0, looks=[L['black_salmon'], L['steel']], switch='beats',
       cam=Cam(depth=1200, extrude=110, extrude_n=6, pivot=(0.5, 0.55)), anim={'yaw': (22, 32, 'lin'), 'zoom': (1.5, 1.7, 'lin')})
E.hit(6.85, 'flash').hit(6.85, 'ca')
# G 回到实时，点被扯散、流走
sync(8.61, 9.98, looks=[L['white_sparse'], L['purple_glow'], L['gold_glow'], L['steel_mid']], switch='beats',
     cam=Cam(dof=1.6, yaw=6), shutter=4, anim={'explode': (0, 1500, 'in')})
E.hit(8.94, 'flash', 0.6)
# H 亮色底 + 彩色残影（素材在动，残影自然拉开）
TR = dict(n=4, step=1, colors=TRAIL, alpha=0.7)
sync(9.98, 11.17, looks=[L['blue_white'], L['orange_black'], L['magenta_white'], L['yellow_black']],
     switch='beats', trail=TR)
E.hits_from_audio(kinds=('burst',), t0=9.9, t1=11.1, min_strength=0.45)
# 11.17 镜头切到刀光特写：原画 + 白闪 + 色散当转场
sync(11.17, 11.35, look=L['steel'], raw=1, ca=18)
E.hit(11.17, 'flash')
sync(11.35, 12.84, looks=[L['cyan_black'], L['cream_navy'], L['orange_black'], L['blue_white']],
     switch='beats', trail={**TR, 'floor': 272})
E.hits_from_audio(kinds=('burst',), t0=11.4, t1=12.8, min_strength=0.4)
# I 加速：每半拍换，压扁
sync(12.84, 14.1, looks=[L['white_sparse'], L['steel'], L['yellow_black'], L['black_pink'], L['gold_glow'],
                         L['blue_white'], L['steel_mid'], L['magenta_white']], switch='halves')
E.hits_from_audio(kinds=('squash', 'ca'), t0=12.8, t1=14.0, min_strength=0.4)
E.hit(13.58, 'burst')
# J 14.1 最后一次火花相撞 → 放射状冲向镜头
E.shot(14.1, 14.65, SRC, src=338, speed=0, look=L['ember'], cam=Cam(dof=2.4),
       shutter=6, anim={'explode': (0, 3600, 'lin'), 'zoom': (1.0, 1.25, 'lin')})
E.hit(14.1, 'flash')
# K 收尾：白点消散，只剩几个大白点
E.shot(14.65, 14.85, SRC, src=352, speed=0, look=L['white_sparse'],
       anim={'look.density': (0.45, 0.12, 'in'), 'look.spacing': (15, 34)})
E.shot(14.85, 15.04, SRC, src=352, speed=0, look=L['white_bokeh'],
       anim={'look.density': (0.15, 0.04), 'look.spacing': (90, 140)})

if __name__ == '__main__':
    E.run(HERE, audio=AUDIO, name='dots')
