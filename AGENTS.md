# AGENTS.md

本仓库是 **dotkit**：把人物视频做成按节拍切换的点阵风短片（@aicreataro《点之战》风格）。纯 Python 命令行工具。

## 用户想做点阵风视频时

**读 `.agents/skills/dotkit/SKILL.md`，按里面的工作流一步步做。** 风格规则在 `docs/STYLE.md`，剪辑脚本参数在 `docs/EDITING.md`。

最短路径：

```bash
python3 -m venv .venv && .venv/bin/pip install -e .   # 第一次
.venv/bin/dotkit doctor && bash tests/smoke.sh          # 环境检查，要看到 SMOKE OK
.venv/bin/dotkit auto 素材.mp4 --out pieces/<名字>       # 出初版：dots.mp4 + compare.mp4 + edit.py
```

## 改 dotkit 本身时

- 代码在 `dotkit/`：`prep.py`（遮罩 + 深度）、`beats.py`（节拍）、`dots.py`（渲染核心）、`looks.py`（look 预设）、`edit.py`（剪辑层）、`auto.py`（自动导演）、`cli.py`（命令行）。
- 改完必须跑 `bash tests/smoke.sh`，看到 `SMOKE OK`。
- 风格上的新经验写进 `docs/STYLE.md`，参数变化写进 `docs/EDITING.md`；不要在 AGENTS.md / SKILL.md 里重复写规则。
- `pieces/` 是用户的作品目录，不提交（见 `.gitignore`）。
