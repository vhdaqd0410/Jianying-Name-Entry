# -*- coding: utf-8 -*-
"""投送语义验证: 整批完成后统一剪切 / 只搬本次产物 / 同名冲突四种策略。"""
import sys, os, tempfile, shutil, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement',
               'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)

fails = []
def ck(name, cond, extra=''):
    print(('  [OK] ' if cond else '  [FAIL] ') + name + (('  ' + str(extra)) if extra else ''))
    if not cond: fails.append(name)

TMP = tempfile.mkdtemp(prefix='deliver_')
OUT = os.path.join(TMP, '输出')
FIN = os.path.join(TMP, '最终')
PROJ = os.path.join(FIN, '731-11926-（海外）《合约八年，我成了自己的靠山》')
os.makedirs(OUT, exist_ok=True)
os.makedirs(PROJ, exist_ok=True)
TARGET = os.path.join(PROJ, '人名条')

def make_out(name, data=b'X'):
    p = os.path.join(OUT, name)
    open(p, 'wb').write(data)
    return p

def mk(policy='ask', cb=None, move=True):
    return gb.BatchRunner(None, OUT, log_cb=lambda m: LOG.append(m),
                          final_root=FIN, final_title='合约八年我成了自己的靠山',
                          final_move=move, conflict_policy=policy, conflict_cb=cb)

LOG = []

# ============ 1. 只搬本次产物; 输出目录里的其它文件不动 ============
print('--- 只搬本次产物 ---')
LOG.clear()
stray = make_out('别人放的.mp4', b'STRAY')      # 不是本次产物
mine1 = make_out('Iris.mp4', b'IRIS')
mine2 = make_out('Iris_透明.mov', b'MOV')
r = mk('rename')
r._produced = [mine1, mine2]
r.deliver_all(['Iris'])
ck('本次产物已搬走', not os.path.exists(mine1) and os.path.exists(os.path.join(TARGET, 'Iris.mp4')))
ck('透明文件一起搬', os.path.exists(os.path.join(TARGET, 'Iris_透明.mov')))
ck('非本次文件留在原地', os.path.exists(stray), stray)
ck('非本次文件未被送过去', not os.path.exists(os.path.join(TARGET, '别人放的.mp4')))
ck('统计 moved=2', r._final_moved == 2, r._final_moved)

# ============ 2. 输出目录之外的路径被拒绝 ============
print('--- 越界路径被拒 ---')
LOG.clear()
outside = os.path.join(TMP, '外部.mp4'); open(outside, 'wb').write(b'OUT')
r2 = mk('rename'); r2._produced = [outside]
r2.deliver_all(['Iris'])
ck('输出目录外的文件不搬', os.path.exists(outside))
ck('并给出提示', any('跳过非本次输出文件' in m for m in LOG), [m for m in LOG if '跳过' in m])

# ============ 3. 同名冲突: 四种策略 ============
print('--- 同名: rename ---')
LOG.clear()
open(os.path.join(TARGET, 'Ethan.mp4'), 'wb').write(b'OLD')   # 先放一个已存在的同名文件
a = make_out('Ethan.mp4', b'NEW')
r3 = mk('rename'); r3._produced = [a]
r3.deliver_all(['Ethan'])
ck('已存在时改名为 (1)', os.path.exists(os.path.join(TARGET, 'Ethan(1).mp4')))
ck('改名件内容是新的', open(os.path.join(TARGET, 'Ethan(1).mp4'), 'rb').read() == b'NEW')
ck('原文件未被覆盖', open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read() == b'OLD')

print('--- 同名: overwrite ---')
LOG.clear()
b = make_out('Ethan.mp4', b'REPLACED')
r4 = mk('overwrite'); r4._produced = [b]
stat4 = r4.deliver_all(['Ethan'])
ck('覆盖成功', open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read() == b'REPLACED')
ck('统计 overwritten=1', stat4['overwritten'] == 1, stat4)
ck('未额外产生 (1) 之类', not os.path.exists(os.path.join(TARGET, 'Ethan(2).mp4')))

print('--- 同名: skip ---')
LOG.clear()
c = make_out('Ethan.mp4', b'SHOULD_NOT_LAND')
r5 = mk('skip'); r5._produced = [c]
stat5 = r5.deliver_all(['Ethan'])
ck('跳过时目标不变', open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read() == b'REPLACED')
ck('源文件仍在输出目录', os.path.exists(c))
ck('统计 skipped=1', stat5['skipped'] == 1, stat5)

print('--- 同名: ask(回调) ---')
for ans, expect_new in (('overwrite', b'ASKED_OVER'), ('rename', None), ('skip', None), ('cancel', None)):
    LOG.clear()
    d = make_out('Ethan.mp4', b'ASKED_' + ans.encode())
    seen = {}
    def cb(conflicts, _a=ans, _s=seen):
        _s['n'] = len(conflicts); _s['name'] = os.path.basename(conflicts[0][1])
        return _a
    r6 = mk('ask', cb); r6._produced = [d]
    st6 = r6.deliver_all(['Ethan'])
    ck(f'ask→{ans}: 回调收到冲突', seen.get('n') == 1 and seen.get('name') == 'Ethan.mp4', seen)
    if ans == 'overwrite':
        ck('ask→overwrite 已覆盖', open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read() == b'ASKED_overwrite')
    elif ans == 'rename':
        ck('ask→rename 产生新文件', os.path.exists(os.path.join(TARGET, 'Ethan(3).mp4')) or
           len([f for f in os.listdir(TARGET) if f.startswith('Ethan(')]) >= 1)
    elif ans == 'skip':
        ck('ask→skip 源仍在', os.path.exists(d))
    else:
        ck('ask→cancel 源仍在且标记 aborted', os.path.exists(d) and st6['aborted'])

print('--- ask 但无回调: 安全跳过, 绝不覆盖 ---')
LOG.clear()
e = make_out('Ethan.mp4', b'NO_CB')
before = open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read()
r7 = mk('ask', None); r7._produced = [e]
st7 = r7.deliver_all(['Ethan'])
ck('未覆盖已有文件', open(os.path.join(TARGET, 'Ethan.mp4'), 'rb').read() == before)
ck('源文件保留', os.path.exists(e))
ck('统计 skipped=1', st7['skipped'] == 1, st7)

print('--- 不勾剪切(=只复制) ---')
LOG.clear()
f = make_out('Solo.mp4', b'SOLO')
r8 = mk('rename', None, move=False); r8._produced = [f]
r8.deliver_all(['Solo'])
ck('原件保留', os.path.exists(f))
ck('副本已到', os.path.exists(os.path.join(TARGET, 'Solo.mp4')))

print('--- 匹配失败: 全部留在输出目录 ---')
LOG.clear()
g = make_out('Orphan.mp4', b'ORPH')
r9 = gb.BatchRunner(None, OUT, log_cb=lambda m: LOG.append(m),
                    final_root=FIN, final_title='根本不存在的剧名XYZ')
r9._produced = [g]
st9 = r9.deliver_all(['Orphan'])
ck('文件未动', os.path.exists(g))
ck('日志说明未定位', any('未定位到项目文件夹' in m for m in LOG), [m for m in LOG if '未定位' in m])
ck('统计为空', st9['moved'] == 0 and not st9['aborted'])

print('--- 未设最终位置: 完全不动 ---')
LOG.clear()
h = make_out('NoFinal.mp4', b'NF')
r10 = gb.BatchRunner(None, OUT, log_cb=lambda m: LOG.append(m))
r10._produced = [h]
ck('无动作', r10.deliver_all(['NoFinal'])['moved'] == 0 and os.path.exists(h))

# ============ 4. 整批完成后才投送（关键: 循环期不能搬） ============
print('--- 逐条阶段不搬, 批次结束才搬 ---')
LOG.clear()
for f_ in os.listdir(TARGET):
    os.remove(os.path.join(TARGET, f_))

class ProbeRunner(gb.BatchRunner):
    """模拟批量: process_one 只造文件并登记; 记录每次调用时最终目录的内容。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.snapshots = []

    def process_one(self, name, before_set):
        self.snapshots.append(sorted(os.listdir(TARGET)) if os.path.isdir(TARGET) else [])
        p = os.path.join(self._outdir_actual, name + '.mp4')
        open(p, 'wb').write(('DATA' + name).encode())
        self._produced.append(p)
        self.progress_cb(0, 1, name, 'ok')
        return True

pr = ProbeRunner(None, OUT, log_cb=lambda m: LOG.append(m),
                 final_root=FIN, final_title='合约八年我成了自己的靠山',
                 conflict_policy='rename')
names = ['Adam', 'Ben', 'Cara']
pr.run(names)
ck('处理过程中最终目录一直是空的', all(s == [] for s in pr.snapshots), pr.snapshots)
ck('三个成片都已投送', all(os.path.exists(os.path.join(TARGET, n + '.mp4')) for n in names))
ck('run_log 也投送了', os.path.exists(os.path.join(TARGET, 'run_log.csv')))
ck('本批三个成片已离开输出目录(剪切)',
   [x for x in os.listdir(OUT) if x.split('.')[0] in names] == [], os.listdir(OUT))
ck('前面用例刻意留下的文件仍在', os.path.exists(os.path.join(OUT, 'NoFinal.mp4')) and
   os.path.exists(os.path.join(OUT, '别人放的.mp4')))
ck('日志有投送阶段标题', any('输出完成, 开始投送' in m for m in LOG), [m for m in LOG if '投送' in m])
ck('produced 只含 3 成片 + run_log', len(pr._produced) == 4, pr._produced)

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
