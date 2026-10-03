#!/usr/bin/env bash
# 冒烟测试：合成一段 6 秒的「纯色背景 + 两个色块在动 + 120 BPM 鼓点」视频，走一遍 dotkit auto。
# 不下载模型（--mask key --depth flat），约 20–40 秒。看到 SMOKE OK 就说明环境和整条管线是好的。
#   bash tests/smoke.sh            # 快速版
#   bash tests/smoke.sh --models   # 再用分割 + 深度模型预处理 1 秒（第一次会下载约 300MB 模型）
set -euo pipefail
PY=${PYTHON:-python3}
T=$(mktemp -d "${TMPDIR:-/tmp}/dotkit-smoke.XXXXXX")
echo "临时目录 $T"
ffmpeg -v error -y \
  -f lavfi -i "color=c=0xE04A2A:s=960x540:r=24:d=6" \
  -f lavfi -i "aevalsrc='0.8*sin(2*PI*70*t)*exp(-25*mod(t\,0.5))':s=44100:d=6" \
  -vf "drawbox=x='200+120*sin(t*2.2)':y=150:w=150:h=300:color=0x1B2342:t=fill,drawbox=x='560+90*sin(t*3.1+1)':y=170:w=130:h=280:color=0xF2E6D3:t=fill,drawbox=x='240+120*sin(t*2.2)':y=110:w=70:h=60:color=0x2E3A66:t=fill" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$T/clip.mp4"
$PY -m dotkit doctor
$PY -m dotkit auto "$T/clip.mp4" --out "$T/piece" --mask key --depth flat --workers 4
$PY - "$T/piece" <<'PYEOF'
import json, subprocess, sys
d = sys.argv[1]
def probe(p, what):
    return subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', what,
                           '-show_entries', 'stream=nb_read_frames,nb_read_packets', '-of', 'csv=p=0', p],
                          capture_output=True, text=True).stdout.strip()
n = int(probe(f'{d}/dots.mp4', 'v:0').split(',')[0])
assert 130 <= n <= 146, f'dots.mp4 帧数不对：{n}'
assert probe(f'{d}/dots.mp4', 'a:0'), 'dots.mp4 没有声音'
assert probe(f'{d}/compare.mp4', 'v:0'), 'compare.mp4 没生成'
m = json.load(open(f'{d}/src/meta.json'))
assert m['frames'] == 144 and max(m['area']) > 0.05, f'预处理异常：{m["frames"]} 帧，人物面积 {max(m["area"])}'
print(f'dots.mp4 {n} 帧，有声音；compare.mp4 OK')
PYEOF
if [[ "${1:-}" == "--models" ]]; then
  $PY -m dotkit prep "$T/clip.mp4" "$T/model_src" --dur 1
fi
echo "SMOKE OK"
