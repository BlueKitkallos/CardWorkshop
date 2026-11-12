import subprocess

_watchers = []


def die_with_parent(pid):
    _watchers[:] = [w for w in _watchers if w.poll() is None]
    script = (f'while kill -0 {pid} 2>/dev/null; do read -t 5 _; '
              f'[ $? -eq 1 ] && {{ kill -KILL -{pid} 2>/dev/null; exit; }}; done')
    _watchers.append(subprocess.Popen(['bash', '-c', script], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True))
