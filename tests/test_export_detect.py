# -*- coding: utf-8 -*-
"""导出文件检测: 不依赖文件名前缀 / 多目录 / 时间窗 / 超时取证。"""
import sys, os, time, tempfile, shutil, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement', 'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = r'F:\OH-WorkSpace\projects\Jianying-Name-Entry'
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)

fails = []
def ck(n, c, e=''):
    print(('  [OK] ' if c else '  [FAIL] ') + n + (('  ' + str(e)) if e else ''))
    if not c: fails.append(n)

TMP = tempfile.mkdtemp(prefix='exp_')
EXPDIR = os.path.join(TMP, '剪映导出'); os.makedirs(EXPDIR)
OUT = os.path.join(TMP, '输出'); os.makedirs(OUT)
LOG = []
def mk(**kw):
    kw.setdefault('log_cb', lambda m: LOG.append(m))
    kw.setdefault('export_dir', EXPDIR)
    return gb.BatchRunner(None, OUT, **kw)

print('--- 候选目录 ---')
r = mk()
dirs = r.export_dirs()
print('  扫描目录:', dirs)
ck('包含指定导出目录', EXPDIR in dirs, dirs)
ck('包含输出目录', OUT in dirs, dirs)
ck('目录不重复', len(dirs) == len(set(dirs)), dirs)

print()
print('--- 关键: 不依赖文件名前缀也能认出新文件 ---')
before = r._snapshot_exports()
ck('初始快照不含东西', len([k for k in before if k.startswith(EXPDIR)]) == 0, len(before))

# 造一个名字完全不同(模拟别的电脑草稿名不同)的新导出
newf = os.path.join(EXPDIR, '随便什么草稿名 2026-01-01.mp4')
open(newf, 'wb').write(b'x' * 1024)
hit = r._diff_exports(before)
ck('名字不匹配前缀也能认出来', hit == newf, hit)

print()
print('--- 已存在的旧文件不会被误认 ---')
shot = r._snapshot_exports()
hit2 = r._diff_exports(shot)
ck('无变化时返回 None', hit2 is None, hit2)

print()
print('--- 旧文件(超过时间窗)不算新导出 ---')
oldf = os.path.join(EXPDIR, '很久以前的片子.mp4')
open(oldf, 'wb').write(b'y' * 512)
old_time = time.time() - 3600 * 5      # 5 小时前
os.utime(oldf, (old_time, old_time))
hit3 = r._diff_exports({})
ck('超过 10 分钟的文件不算', hit3 != oldf, hit3)

print()
print('--- 变化的文件也算(同名被重新导出) ---')
f2 = os.path.join(EXPDIR, '重导.mp4')
open(f2, 'wb').write(b'z' * 100)
shot2 = r._snapshot_exports()
time.sleep(0.05)
open(f2, 'wb').write(b'z' * 5000)      # 大小变化
hit4 = r._diff_exports(shot2)
ck('文件变大后能认出来', hit4 == f2, hit4)

print()
print('--- 优先级: 带剪映默认前缀的优先 ---')
D2 = os.path.join(TMP, '导出2'); os.makedirs(D2)
r2 = mk(export_dir=D2)
open(os.path.join(D2, '普通名字.mp4'), 'wb').write(b'a')
open(os.path.join(D2, '海外人名条 1.mp4'), 'wb').write(b'b')
h = r2._diff_exports({})
ck('优先返回带默认前缀的', '海外人名条' in (h or ''), h)

print()
print('--- 快照包含 mov ---')
mv = os.path.join(EXPDIR, '透明.mov')
open(mv, 'wb').write(b'q')
snap3 = r._snapshot_exports()
ck('快照含 .mov', mv in snap3)
ck('快照不含非视频文件', not any(x.endswith('.txt') for x in snap3))

print()
print('--- 超时会把扫描目录写进日志(取证) ---')
LOG.clear()
# 先把现有文件全部入快照, 这样轮询期间不会有“新文件”, 才能真的走到超时
r3 = mk()
base = r3._snapshot_exports()
got = r3.wait_new_export(base, timeout=1)
ck('超时返回 None', got is None, got)
joined = '\n'.join(LOG)
ck('日志列出扫描过的目录', EXPDIR in joined or OUT in joined,
   [l for l in LOG if '扫描' in l or '目录' in l][:4])
ck('日志提示去确认导出位置', '导出' in joined, [l for l in LOG][-4:])

print()
print('--- 兼容旧接口(传 set 也能用) ---')
r4 = mk()
# 先把现有文件入快照, 再新增一个
old_style = set(r4._scan_exports())
nf = os.path.join(EXPDIR, '兼容测试2.mp4')
open(nf, 'wb').write(b'k')
hit5 = r4.wait_new_export(old_style, timeout=3)
ck('旧的 set 接口仍可用', hit5 == nf, hit5)

print()
print('--- export_dir 为空时仍能扫常见目录 ---')
r5 = gb.BatchRunner(None, OUT, log_cb=lambda m: None)
dirs5 = r5.export_dirs()
ck('至少有输出目录', OUT in dirs5, dirs5)
ck('不会因 export_dir 为空而崩', len(dirs5) >= 1)

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
