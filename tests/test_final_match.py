# -*- coding: utf-8 -*-
"""剧名归一化 / 项目文件夹匹配 验证（离线，不连剪映）。"""
import sys, os, tempfile, shutil, importlib.util, types
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 只验纯逻辑, 给 uiautomation 打桩, 避开环境依赖
if 'uiautomation' not in sys.modules:
    stub = types.ModuleType('uiautomation')
    for _n in ('Control', 'WindowControl', 'GetRootControl', 'AutomationElement',
               'SetGlobalSearchTimeout'):
        setattr(stub, _n, type(_n, (), {}))
    sys.modules['uiautomation'] = stub

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根(tests 的上一级)
spec = importlib.util.spec_from_file_location('gb', os.path.join(HERE, 'gui_batch.pyw'))
gb = importlib.util.module_from_spec(spec); spec.loader.exec_module(gb)

fails = []
def ck(name, cond, extra=''):
    print(('  [OK] ' if cond else '  [FAIL] ') + name + (('  ' + str(extra)) if extra else ''))
    if not cond: fails.append(name)

print('--- clean_title (显示用, 保留可读标点) ---')
ck('去序号+后缀', gb.clean_title('32_合约八年我成了自己的靠山_角色场景表') == '合约八年我成了自己的靠山',
   gb.clean_title('32_合约八年我成了自己的靠山_角色场景表'))
ck('英文剧名不动', gb.clean_title('My Husband Thinks I am Obsessed with Him-2') == 'My Husband Thinks I am Obsessed with Him-2')

print('--- norm_title (比较用, 全量归一化) ---')
ck('去序号+后缀+标点', gb.norm_title('32_合约八年我成了自己的靠山_角色场景表.csv') == '合约八年我成了自己的靠山',
   gb.norm_title('32_合约八年我成了自己的靠山_角色场景表.csv'))
ck('去多层序号前缀', gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》') == '海外合约八年我成了自己的靠山',
   gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》'))
ck('单层字母数字前缀保留', gb.norm_title('H0242-11947《我的便宜老公是总裁》') == 'h024211947我的便宜老公是总裁',
   gb.norm_title('H0242-11947《我的便宜老公是总裁》'))
ck('转小写', gb.norm_title('My Husband Thinks I’m Obsessed with Him-2') == 'myhusbandthinksimobsessedwithhim2',
   gb.norm_title('My Husband Thinks I’m Obsessed with Him-2'))
ck('剧名是项目名子串',
   gb.norm_title('合约八年我成了自己的靠山') in gb.norm_title('731-11926-（海外）《合约八年，我成了自己的靠山》'))

print('--- 真实 O 盘匹配(不依赖具体项目名, 目录会变) ---')
REAL_ROOT = r'O:\AI漫剧剪辑一组'
if os.path.isdir(REAL_ROOT):
    subs = [d for d in os.listdir(REAL_ROOT) if os.path.isdir(os.path.join(REAL_ROOT, d))]
    print(f'  根目录下 {len(subs)} 个项目文件夹')
    hit = 0
    for d in subs:
        # 用文件夹自身的名字去反查, 应当能命中自己
        proj, why = gb.match_project(REAL_ROOT, d)
        if proj == d:
            hit += 1
        else:
            print(f'    未命中: {d!r} -> {proj!r} ({why})')
    ck(f'每个项目都能用自己的名字命中自己 ({hit}/{len(subs)})', hit == len(subs) or len(subs) == 0)
    # 含《》的剧名(最典型的形态) 抽一个验
    titled = [d for d in subs if '《' in d]
    if titled:
        d = titled[0]
        inner = d.split('《', 1)[1].split('》', 1)[0]
        proj, why = gb.match_project(REAL_ROOT, inner)
        ck(f'从书名号里取剧名能命中 ({inner[:10]}…)', proj == d, f'{proj!r} {why}')
else:
    print('  (O 盘不可见, 跳过)')

print('--- 名字集合兜底 ---')
fake = tempfile.mkdtemp(prefix='projmatch_')
projA = os.path.join(fake, 'AAA-0001《未知剧名甲》'); os.makedirs(os.path.join(projA, '人名条'))
projB = os.path.join(fake, 'BBB-0002《未知剧名乙》'); os.makedirs(os.path.join(projB, '人名条'))
for n in ['Alice', 'Bob', 'Cindy', 'Dan']:
    open(os.path.join(projA, '人名条', n + '.mp4'), 'w').write('x')
open(os.path.join(projB, '人名条', 'Zoe.mp4'), 'w').write('x')
proj, why = gb.match_project(fake, '完全不相干的剧名', ['Alice', 'Bob', 'Cindy', 'Dan'])
ck('名字兜底命中 A', proj == os.path.basename(projA), f'{proj!r} {why}')
ck('重合度不足则不猜', gb.match_project(fake, '完全不相干的剧名', ['Q1', 'Q2', 'Q3'])[0] is None)
ck('剧名子串优先于名字兜底', gb.match_project(fake, '未知剧名乙')[0] == os.path.basename(projB))
ck('根目录不存在返回None', gb.match_project(os.path.join(fake, 'nope'), 'x')[0] is None)

print('--- 冲突策略枚举 ---')
ck('默认策略含询问', 'ask' in gb.CONFLICT_LABELS.values())
ck('标签与值一一对应', set(gb.FROM_CONFLICT_VALUE.values()) == set(gb.CONFLICT_LABELS.keys()))
ck('往返一致', all(gb.FROM_CONFLICT_VALUE[v] == k for k, v in gb.CONFLICT_LABELS.items()))

shutil.rmtree(fake, ignore_errors=True)
print()
if fails:
    print(f'FAILED {len(fails)}: ' + '; '.join(fails)); sys.exit(1)
print('ALL PASS')
