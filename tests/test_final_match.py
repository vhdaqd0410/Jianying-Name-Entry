# -*- coding: utf-8 -*-
"""验证项目文件夹匹配 + 剪切到 项目\人名条\ 的逻辑。"""
import sys, os, tempfile, shutil, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 本测试只验文件逻辑, 不需要连剪映; 先给 uiautomation 打个桩, 避开环境依赖
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement',
               'DocumentControl', 'EditControl', 'PaneControl', 'ButtonControl',
               'ListItemControl', 'TextControl', 'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    stub.uiautomation = stub
    sys.modules['uiautomation'] = stub

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)

fails = []
def ck(name, cond, extra=''):
    print(('  [OK] ' if cond else '  [FAIL] ') + name + (('  ' + str(extra)) if extra else ''))
    if not cond: fails.append(name)

# ================= 1. 归一化 =================
print('--- norm_title ---')
ck('去序号+后缀+标点', gb.norm_title('32_合约八年我成了自己的靠山_角色场景表.csv') == '合约八年我成了自己的靠山',
   gb.norm_title('32_合约八年我成了自己的靠山_角色场景表.csv'))
ck('去多层序号前缀', gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》') == '海外合约八年我成了自己的靠山',
   gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》'))
ck('去单层序号前缀', gb.norm_title('H0242-11947《我的便宜老公是总裁》') == 'h024211947我的便宜老公是总裁',
   gb.norm_title('H0242-11947《我的便宜老公是总裁》'))
ck('转小写', gb.norm_title('My Husband Thinks I’m Obsessed with Him-2') == 'myhusbandthinksimobsessedwithhim2',
   gb.norm_title('My Husband Thinks I’m Obsessed with Him-2'))

print('--- 子串命中 ---')
t = gb.norm_title('合约八年我成了自己的靠山_角色场景表.csv')
p = gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》')
ck('剧名是项目名子串', t in p, f'{t} in {p}')

# ================= 2. 真实 O 盘匹配 =================
print('--- 真实 O 盘匹配 ---')
REAL_ROOT = r'O:\AI漫剧剪辑一组'
if os.path.isdir(REAL_ROOT):
    cases = [
        ('合约八年我成了自己的靠山_角色场景表', '731-11926-（海外）《合约八年，我成了自己的靠山》'),
        ('死而复生双胞胎的终极复仇_角色场景表', '734-11682-（海外）《死而复生：双胞胎的终极复仇》'),
        ('我的便宜老公是总裁_角色场景表', 'H0242-11947《我的便宜老公是总裁》'),
        ('觉醒后我能听懂海洋心声_角色场景表', 'H0251-12154《觉醒后我能听懂海洋心声》'),
        ('一夜沦陷亿万大佬的绝美娇妻_角色场景表', 'H0226-11823 《一夜沦陷：亿万大佬的绝美娇妻》'),
    ]
    for title, expect in cases:
        proj, why = gb.match_project(REAL_ROOT, title)
        ck(f'匹配 {title[:12]}…', proj == expect, f'得到 {proj!r} 依据 {why}')
else:
    print('  (O 盘不可见, 跳过)')

# ================= 3. 兜底: 用已有成片名字 =================
print('--- 名字集合兜底 ---')
fake = tempfile.mkdtemp(prefix='projmatch_')
projA = os.path.join(fake, 'AAA-0001《未知剧名甲》'); os.makedirs(os.path.join(projA, '人名条'))
projB = os.path.join(fake, 'BBB-0002《未知剧名乙》'); os.makedirs(os.path.join(projB, '人名条'))
for n in ['Alice', 'Bob', 'Cindy', 'Dan']: open(os.path.join(projA, '人名条', n + '.mp4'), 'w').write('x')
open(os.path.join(projB, '人名条', 'Zoe.mp4'), 'w').write('x')
proj, why = gb.match_project(fake, '完全不相干的剧名', ['Alice', 'Bob', 'Cindy', 'Dan'])
ck('名字兜底命中 A', proj == os.path.basename(projA), f'{proj!r} {why}')
proj2, why2 = gb.match_project(fake, '完全不相干的剧名', ['Q1', 'Q2', 'Q3'])
ck('重合度不足则不猜', proj2 is None, f'{proj2!r} {why2}')
proj3, why3 = gb.match_project(fake, '未知剧名乙')
ck('剧名子串优先于名字兜底', proj3 == os.path.basename(projB), f'{proj3!r} {why3}')
ck('根目录不存在返回None', gb.match_project(os.path.join(fake, 'nope'), 'x')[0] is None)

# ================= 4. 剪切到 项目\人名条\ =================
print('--- 剪切行为 ---')
out_root = os.path.join(fake, '输出'); os.makedirs(out_root, exist_ok=True)
fin_root = os.path.join(fake, '最终'); 
os.makedirs(os.path.join(fin_root, '731-11926-（海外）《合约八年，我成了自己的靠山》', '人名条'))

src = os.path.join(out_root, 'Iris.mp4'); open(src, 'wb').write(b'I' * 200)
src2 = os.path.join(out_root, 'Iris_透明.mov'); open(src2, 'wb').write(b'T' * 100)

logs = []
r = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                   final_root=fin_root, final_title='合约八年我成了自己的靠山_角色场景表',
                   final_move=True)
d = r.resolve_final_dir(['Iris'])
ck('定位到正确目录', d.endswith(os.path.join('《合约八年，我成了自己的靠山》', '人名条')), d)
ck('第二次调用复用缓存', r.resolve_final_dir() == d)
r._deliver_final([src, src2])
dst_dir = os.path.join(fin_root, '731-11926-（海外）《合约八年，我成了自己的靠山》', '人名条')
ck('mp4 已剪切过去', os.path.exists(os.path.join(dst_dir, 'Iris.mp4')))
ck('透明 mov 也一起过去', os.path.exists(os.path.join(dst_dir, 'Iris_透明.mov')))
ck('输出目录原件已消失(剪切)', not os.path.exists(src) and not os.path.exists(src2))
ck('计数=2', r._final_moved == 2, r._final_moved)
ck('内容完整', open(os.path.join(dst_dir, 'Iris.mp4'), 'rb').read() == b'I' * 200)

print('--- 同名不覆盖 ---')
open(src, 'wb').write(b'X' * 10)
r._deliver_final([src])
ck('同名加 (1)', os.path.exists(os.path.join(dst_dir, 'Iris(1).mp4')))
ck('原文件未被覆盖', open(os.path.join(dst_dir, 'Iris.mp4'), 'rb').read() == b'I' * 200)

print('--- 不勾剪切时只复制 ---')
src3 = os.path.join(out_root, 'Solo.mp4'); open(src3, 'wb').write(b'S')
r2 = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                    final_root=fin_root, final_title='合约八年我成了自己的靠山', final_move=False)
r2.resolve_final_dir(['Solo']); r2._deliver_final([src3])
ck('原件保留', os.path.exists(src3))
ck('副本存在', os.path.exists(os.path.join(dst_dir, 'Solo.mp4')))

print('--- 匹配失败不乱放 ---')
src4 = os.path.join(out_root, 'Orphan.mp4'); open(src4, 'wb').write(b'O')
r3 = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                    final_root=fin_root, final_title='根本不存在的剧名XYZ')
r3.resolve_final_dir(['Orphan']); r3._deliver_final([src4])
ck('未匹配时文件留在原地', os.path.exists(src4))
ck('日志报告未定位', any('未定位到项目文件夹' in m for m in logs), [m for m in logs if '未定位' in m])
ck('最终目录为空', r3._final_dir == '')

print('--- 根目录不存在 ---')
r4 = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                    final_root=os.path.join(fake, '不存在'), final_title='x')
ck('根目录不存在时跳过', r4.resolve_final_dir(['a']) == '')

print('--- 自动建 人名条 子目录 ---')
projC = os.path.join(fin_root, '999-测试《新建子目录的剧》'); os.makedirs(projC)
src5 = os.path.join(out_root, 'New.mp4'); open(src5, 'wb').write(b'N')
r5 = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                    final_root=fin_root, final_title='新建子目录的剧', final_move=True)
d5 = r5.resolve_final_dir(['New'])
ck('自动建出 人名条', os.path.isdir(d5) and d5.endswith('人名条'), d5)
r5._deliver_final([src5])
ck('文件进入新目录', os.path.exists(os.path.join(d5, 'New.mp4')))

print('--- 子文件夹名可自定义 ---')
r6 = gb.BatchRunner(None, out_root, log_cb=lambda m: logs.append(m),
                    final_root=fin_root, final_title='新建子目录的剧', final_subdir='人名条_竖版')
d6 = r6.resolve_final_dir(['New'])
ck('自定义子文件夹生效', d6.endswith('人名条_竖版'), d6)

shutil.rmtree(fake, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
