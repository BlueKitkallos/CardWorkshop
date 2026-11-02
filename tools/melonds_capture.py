#!/usr/bin/env python3
"""Play a ROM in melonDS yourself and record it: only the two DS screens, only the game's sound."""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MELON = os.environ.get('MELON', os.path.expanduser('~/tools/melonds/squashfs-root/AppRun'))
BASE_CFG = os.environ.get('CAPTURE_BASE_CFG', os.path.expanduser('~/tools/melonds/cfg_rec'))
CFG = os.path.expanduser('~/tools/melonds/cfg_capture')
SINK = f'ygo_capture_{os.getpid()}'
APP = f'melonDS_capture_{os.getpid()}'


def audio_env(sink=SINK):
    return {'SDL_AUDIODRIVER': 'pulseaudio', 'PULSE_SINK': sink, 'PULSE_PROP': f'application.name={APP}',
            'SDL_AUDIO_DEVICE_APP_NAME': APP}
RATE = 48000
SPEED = 60 / 59.8261


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def make_config():
    os.makedirs(os.path.join(CFG, 'melonDS'), exist_ok=True)
    src = os.path.join(BASE_CFG, 'melonDS')
    for f in os.listdir(src):
        if f != 'melonDS.toml' and not os.path.exists(os.path.join(CFG, 'melonDS', f)):
            shutil.copy(os.path.join(src, f), os.path.join(CFG, 'melonDS', f))
    t = open(os.path.join(src, 'melonDS.toml')).read()
    for key, val in (('ShowOSD', 'false'), ('IntegerScaling', 'true'), ('ScreenFilter', 'false'), ('ScreenLayout', '0'),
                     ('ScreenSizing', '0'), ('ScreenRotation', '0'), ('ScreenGap', '0'), ('ScreenSwap', 'false'),
                     ('Volume', '256'), ('Interpolation', '3'), ('BitDepth', '2'), ('AudioSync', 'true'), ('LimitFPS', 'true'), ('Hide', 'true'),
                     ('HideSeconds', '1')):
        t = re.sub(rf'(?m)^{key} = .*$', f'{key} = {val}', t)
    t = re.sub(r'(?m)^RecentROM = .*$', 'RecentROM = []', t)
    open(os.path.join(CFG, 'melonDS', 'melonDS.toml'), 'w').write(t)


def default_sink():
    return sh('pactl', 'get-default-sink').stdout.strip()


def load_audio(listen):
    mods = [sh('pactl', 'load-module', 'module-null-sink', f'sink_name={SINK}',
               f'sink_properties=device.description={SINK}', check=True).stdout.strip()]
    if listen:
        mods.append(sh('pactl', 'load-module', 'module-loopback', f'source={SINK}.monitor', f'sink={default_sink()}',
                       'latency_msec=30', check=True).stdout.strip())
    return mods


def melon_on_sink():
    sinks = {s['index']: s['name'] for s in json.loads(sh('pactl', '-f', 'json', 'list', 'sinks').stdout)}
    on = [i['properties'].get('application.name') for i in json.loads(sh('pactl', '-f', 'json', 'list', 'sink-inputs').stdout)
          if sinks.get(i['sink']) == SINK]
    if len(on) > 1:
        raise SystemExit(f'{SINK} has {len(on)} streams ({", ".join(map(str, on))}): only the recorded melonDS may play into it')
    return on == [APP]


def find_window(env, pid):
    for _ in range(150):
        r = sh('xdotool', 'search', '--name', 'melonDS', env=env).stdout.split()
        if r:
            return r[0]
        time.sleep(0.1)
    raise SystemExit('melonDS window not found')


def geometry(env, win):
    out = sh('xdotool', 'getwindowgeometry', '--shell', win, env=env).stdout
    g = dict(line.split('=') for line in out.split())
    return int(g['X']), int(g['Y']), int(g['WIDTH']), int(g['HEIGHT'])


def monitors(env):
    out = sh('xrandr', '--listmonitors', env=env).stdout
    mons = []
    for m in re.finditer(r'(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)', out):
        w, h, x, y = map(int, m.groups())
        mons.append((x, y, w, h))
    return mons


def screen_area(x, y, w, h):
    s = min(w // 256, h // 384)
    if s < 1:
        raise SystemExit(f'window {w}x{h} is smaller than one DS screen pair')
    cw, ch = 256 * s, 384 * s
    return x + (w - cw) // 2, y + (h - ch) // 2, cw, ch, s


def finish(raw, out, scale, crf):
    vf = f'scale=256:384:flags=area,scale={256 * scale}:{384 * scale}:flags=neighbor,setpts=PTS*{SPEED:.6f}'
    af = f'asetrate={RATE}/{SPEED:.6f},aresample={RATE}:resampler=soxr:precision=28,volume=-1dB'
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-stats', '-y', '-i', raw, '-vf', vf, '-af', af,
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-r', '60',
                    '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', out], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__ + ' melonDS runs fullscreen with integer scaling; the DS screens '
                                 'are recorded with ffmpeg (x11grab, no cursor) and the game sound through a private '
                                 'PulseAudio null sink, so no other program is recorded. You keep hearing the game '
                                 'through a loopback to your default output. Close melonDS or press Ctrl+C to stop; '
                                 'the clip is then encoded to MP4 at native speed (59.83 fps), 4x by default.',
                                 epilog='Keys (config ~/tools/melonds/cfg_capture): A=X, B=Z, X=S, Y=A, L=Q, R=W, '
                                 'Start=Enter, Select=Backspace, touch screen = mouse. Needs X11, PulseAudio or PipeWire '
                                 '(pactl), xdotool, xrandr, ffmpeg.')
    ap.add_argument('rom', nargs='?', default=os.path.join(ROOT, 'build', 'dimension-break.nds'),
                    help='ROM to play (default build/dimension-break.nds; its .sav next to it is used)')
    ap.add_argument('-o', '--out', help='output MP4 (default build/capture/<date-time>.mp4)')
    ap.add_argument('--scale', type=int, default=4, help='output size as a multiple of 256x384 (default 4 = 1024x1536)')
    ap.add_argument('--crf', type=int, default=14, help='x264 quality of the MP4, lower is better (default 14)')
    ap.add_argument('--monitor', type=int, help='xrandr monitor index, only used when no window manager makes the '
                    'window fullscreen (default: the one that fits the largest DS scale)')
    ap.add_argument('--mute', action='store_true', help='do not play the game sound on your speakers while recording')
    ap.add_argument('--keep-raw', action='store_true', help='keep the raw recording (.mkv) next to the MP4')
    a = ap.parse_args()

    if not os.environ.get('DISPLAY') or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        raise SystemExit('needs an X11 session (x11grab cannot read other windows under Wayland)')
    for tool in ('pactl', 'xdotool', 'xrandr', 'ffmpeg'):
        if not shutil.which(tool):
            raise SystemExit(f'{tool} not found')
    rom = os.path.abspath(a.rom)
    if not os.path.exists(rom):
        raise SystemExit(f'{rom}: not found')
    out = os.path.abspath(a.out or os.path.join(ROOT, 'build', 'capture', time.strftime('%Y%m%d-%H%M%S') + '.mp4'))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    raw = os.path.splitext(out)[0] + '.raw.mkv'

    make_config()
    env = dict(os.environ, XDG_CONFIG_HOME=CFG, **audio_env())
    mods = load_audio(not a.mute)
    melon = rec = None
    try:
        mons = monitors(env)
        melon = subprocess.Popen([MELON, '-f', rom], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        win = find_window(env, melon.pid)
        time.sleep(2)
        g = geometry(env, win)
        if (g[2], g[3]) not in [(m[2], m[3]) for m in mons]:
            mon = mons[a.monitor] if a.monitor is not None else max(mons, key=lambda m: min(m[2] // 256, m[3] // 384))
            subprocess.run(['xdotool', 'windowmove', win, str(mon[0]), str(mon[1]), 'windowsize', win, str(mon[2]),
                            str(mon[3])], env=env)
            time.sleep(1)
            g = geometry(env, win)
        x, y, w, h, s = screen_area(*g)
        if not melon_on_sink():
            raise SystemExit(f'melonDS sound is not on {SINK}; nothing recorded')
        print(f'recording the DS screens at {s}x ({w}x{h} at {x},{y}) and the melonDS sound only -> {out}')
        print('close melonDS or press Ctrl+C to stop')
        rec = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-thread_queue_size', '1024',
                                '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '60', '-video_size', f'{w}x{h}',
                                '-i', f'{os.environ["DISPLAY"]}+{x},{y}', '-thread_queue_size', '1024', '-f', 'pulse',
                                '-i', f'{SINK}.monitor', '-copyts', '-c:v', 'libx264', '-preset', 'veryfast',
                                '-crf', '12', '-pix_fmt', 'yuv444p', '-c:a', 'pcm_s16le', raw],
                               stdin=subprocess.PIPE, text=True)
        try:
            melon.wait()
        except KeyboardInterrupt:
            pass
    finally:
        if rec and rec.poll() is None:
            try:
                rec.stdin.write('q')
                rec.stdin.flush()
            except BrokenPipeError:
                pass
            rec.wait(60)
        if melon and melon.poll() is None:
            os.killpg(melon.pid, signal.SIGTERM)
            try:
                melon.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(melon.pid, signal.SIGKILL)
                melon.wait()
        for m in reversed(mods):
            sh('pactl', 'unload-module', m)
    if not rec or not os.path.exists(raw):
        raise SystemExit('nothing recorded')
    print('encoding...')
    finish(raw, out, a.scale, a.crf)
    if not a.keep_raw:
        os.remove(raw)
    print(out)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.default_int_handler)
    main()
