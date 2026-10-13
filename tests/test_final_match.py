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
