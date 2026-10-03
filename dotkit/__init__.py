"""dotkit —— 把人物视频做成按节拍切换的点阵风（灵感：@aicreataro《点之战》）。

剪辑脚本里用：
    from dotkit import Edit, Cam, Look, LOOKS, CYCLE, TRAIL, replace
"""
from dataclasses import replace
from .dots import Look, Cam, Clip, frame
from .looks import LOOKS, CYCLE, TRAIL
from .edit import Edit, ease, compare

__version__ = '0.1.0'
__all__ = ['Edit', 'Cam', 'Look', 'Clip', 'frame', 'LOOKS', 'CYCLE', 'TRAIL', 'replace', 'ease', 'compare']
