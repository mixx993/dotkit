"""音乐 → 节拍网格。打点是这种片子的骨架：每半拍换一次 look，重拍上打击。

用法：dotkit beats <音频或视频> <out.json>
输出：tempo、beats（拍）、halves（半拍）、hits（能量峰 = 打击点），都是秒。
"""
import json, subprocess, sys, tempfile, os
import numpy as np
import librosa


def analyze(path):
    tmp = None
    if not path.lower().endswith(('.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg')):
        tmp = tempfile.mktemp(suffix='.wav')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vn', '-ac', '1', '-ar', '22050', tmp], check=True)
        path = tmp
    y, sr = librosa.load(path, sr=22050)
    if tmp: os.remove(tmp)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time')
    tempo = float(np.atleast_1d(tempo)[0])
    oe = librosa.onset.onset_strength(y=y, sr=sr)
    tt = librosa.times_like(oe, sr=sr)
    pk = librosa.util.peak_pick(oe, pre_max=10, post_max=10, pre_avg=10, post_avg=10,
                                delta=oe.std() * 1.5, wait=8)
    halves = []
    for a, b in zip(beats[:-1], beats[1:]):
        halves += [a, (a + b) / 2]
    if len(beats): halves.append(beats[-1])
    strength = (oe[pk] / oe[pk].max()).tolist() if len(pk) else []
    return dict(tempo=tempo, duration=len(y) / sr, beats=[float(b) for b in beats],
                halves=[float(h) for h in halves], hits=[float(t) for t in tt[pk]], hit_strength=strength)


