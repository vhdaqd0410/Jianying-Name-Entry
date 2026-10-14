# -*- coding: utf-8 -*-
"""跑全部测试(含 UI)并汇总。"""
import subprocess, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
tests = ['test_final_match.py', 'test_deliver_batch.py', 'test_final_dir_ui.py',
         'test_v170_optimize.py', 'test_ui_v180.py']
allok, total = True, 0
for t in tests:
    p = os.path.join(HERE, t)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, '-u', p], capture_output=True, env=env)
    out = r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')
    fails = [l for l in out.splitlines() if '[FAIL]' in l]
    n = out.count('[OK]')
    total += n
    ok = r.returncode == 0
    allok = allok and ok
    print(f'{"PASS" if ok else "FAIL"}  {t:<26} 通过 {n:>3} 项' + (f'  失败 {len(fails)}' if fails else ''))
    for l in fails:
        print('        ' + l.strip())
print(f'\n合计 {total} 项  ' + ('全部通过' if allok else '存在失败'))
sys.exit(0 if allok else 1)
