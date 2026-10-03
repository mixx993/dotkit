---
name: dotkit
description: 把人物视频（打斗、舞蹈、动作片段）做成按音乐节拍切换的点阵风短片（@aicreataro《点之战》那一路）：人物变成点阵，每拍 / 半拍换一种点的画法（半调、剪影、发光散点、原色点），重拍时点被压扁、炸向镜头，中间定格后镜头绕着三维点云转，再加彩色残影。用户说「点阵风」「做成点」「点之战」「halftone / dot matrix 风格视频」「把这段打斗做成点」或给出一段人物视频要做这类风格化时使用。纯 Python（numpy + OpenCV + 分割 / 深度模型），不需要 Blender / AE。
---

# dotkit：点之战风格视频

**先读 `docs/STYLE.md`**（风格规则，为什么这样做）。要改剪辑时读 `docs/EDITING.md`（edit.py 的参数）。

## 工作流（按顺序做）

1. **装环境**（只第一次）。在仓库根目录：
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -e .     # 或者 uv venv && uv pip install -e .
   .venv/bin/dotkit doctor                                  # 要看到「环境 OK」
   bash tests/smoke.sh                                      # 要看到 SMOKE OK（约 1 分钟，不下载模型）
   ```
   需要系统里有 ffmpeg。第一次处理真实素材会从 Hugging Face 下载约 300MB 模型。

2. **检查素材**：`ffprobe` 看时长和有没有声音。适合的素材：1–2 个人、动作大、背景简单、5–20 秒。不合适就先告诉用户（多人群戏、人很小、背景很乱效果会差）。

3. **一条命令出初版**：
   ```bash
   .venv/bin/dotkit auto 素材.mp4 --out pieces/<名字>                  # 用素材自带的声音（画面和声音同步）
   .venv/bin/dotkit auto 素材.mp4 --audio 音乐.mp3 --out pieces/<名字>  # 另配音乐
   ```
   输出：`pieces/<名字>/dots.mp4`（成片）、`compare.mp4`（上原画下点阵）、`edit.py`（剪辑脚本）、`beats.json`。
   预处理约 0.5 秒 / 帧（Apple Silicon / NVIDIA）；渲染 15 秒片子约 1 分钟。
   只想先看段落安排：加 `--plan-only`。

4. **自己看结果再交付**。用 ffmpeg 抽帧拼图检查（例如 `ffmpeg -i dots.mp4 -vf "fps=2,scale=320:-1,tile=8x4" -frames:v 1 sheet.png`），对照 `docs/STYLE.md` §6 的规则：
   - 人认得出来吗？（认不出：点距调小、burst 减少）
   - 定格环绕时有没有横向短线糊成一片？（换成密的 look）
   - 残影有没有糊满画面？（`n` 减到 3–4，`step=1`）
   - 镜头切点有没有转场？（`dotkit auto` 会自动在检测到的切点加白闪）

5. **按用户意见改 `edit.py`**，只重渲染改动的那段：`.venv/bin/python pieces/<名字>/edit.py --frames 160 210`，满意了再跑全片 `.venv/bin/python pieces/<名字>/edit.py`。改完 `edit.py` 后**不要**再用 `dotkit auto --overwrite`，会覆盖用户的改动。

6. **交付**：给用户 `dots.mp4` 和 `compare.mp4` 的路径，说明段落安排（`dotkit auto` 打印的时间表）和你做过的调整。

## 硬规则

- 不要把参考作品《点之战》的画面或用户的素材上传、提交到任何地方，除非用户明确要求。
- 不要手写新的渲染代码；所有画法都在 `dotkit/dots.py` 和 `dotkit/looks.py`，组合参数就够了。真缺功能时再改 dotkit，并跑一遍 `tests/smoke.sh`。
- 素材里人物很暗（黑衣服）时，确认用的是暗素材模式（`dotkit auto` 打印「暗素材模式」，或 `--style dark`）。
- 没有 GPU / MPS 时预处理很慢（3–6 秒 / 帧）。素材是纯色背景时可以用 `--mask key --depth flat` 跳过模型（但不能转机位）。

## 其他命令

```bash
dotkit looks pieces/<名字>/src --frame 120 --levels   # 所有 look 画在同一帧上，挑颜色用
dotkit compare 原视频.mp4 dots.mp4 compare.mp4         # 上下对照
dotkit prep / dotkit beats                             # 单独做预处理 / 测节拍
```
