# -*- coding: utf-8 -*-
"""GeeZip —— 让遥感数据"压缩了再下载"。只有这一个入口。

    python run.py 自检       换电脑第一件事
    python run.py 取数       云端随机取样（只下几万个像元，不是整幅）
    python run.py 训练       本地训编码器+解码器（量化感知）
    python run.py 导权重     编码器搬上 GEE，生成 JS 脚本
    python run.py 门禁       ★ 两道核对，不过就挡住后面
    python run.py 下载       云端编码，只把隐层拉回来
    python run.py 解码       本地还原 + 与原图对比出图
    python run.py 汇总       把所有结果收拢成一份报告
    python run.py 全部       上面一整串
    python run.py 外推       换一块没训练过的地，验泛化
    python run.py 新建 "D:\\某目录"   在别处开一条新管线

参数原样透传，例如：
    python run.py 取数 --scene landsat季度 --roi 102.6 24.9 102.8 25.1
    python run.py 训练 --k扫 2 3 4 6
    python run.py 下载 --k 6 --roi 101.4 25.4 101.6 25.6 --标签 外推
"""
import os
import sys
import shutil
import subprocess

这里 = os.path.dirname(os.path.abspath(__file__))
步骤目录 = os.path.join(这里, '引擎', '步骤')

步骤 = {
    '自检': '自检.py',
    '取数': '取数.py',
    '训练': '训练.py',
    '导权重': '导权重.py',
    '门禁': '门禁.py',
    '下载': '下载.py',
    '解码': '解码.py',
    '汇总': '汇总.py',
}

全部顺序 = ['取数', '训练', '导权重', '门禁', '下载', '解码', '汇总']

# 「全部」串跑时，各步用 parse_known_args 忽略不属于自己的参数
#（见 引擎/配置.py 的 解析()）。这里只需要把汇总排除在外 —— 它不吃任何参数。
不吃任何 = {'汇总'}


def 跑(脚本, 参数, 串跑=False):
    cmd = [sys.executable, os.path.join(步骤目录, 脚本)] + list(参数)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if 串跑:
        env['GEEZIP_CHAIN'] = '1'          # 让本步忽略不属于它的参数
    # ★ 先 flush：父进程 print 有缓冲，子进程直接写 stdout，
    #   不 flush 的话标题会被子进程输出抢在前面。
    sys.stdout.flush()
    r = subprocess.run(cmd, env=env)
    sys.stdout.flush()
    return r.returncode


def 摘参数(参数, 去掉键):
    出, 跳 = [], False
    for i, x in enumerate(参数):
        if 跳:
            跳 = False
            continue
        if x in 去掉键:
            # 带值的选项要连值一起摘
            跳 = (i + 1 < len(参数) and not 参数[i + 1].startswith('--'))
            continue
        出.append(x)
    return 出


def 新建(参数):
    if not 参数:
        print('用法：python run.py 新建 "D:\\某目录"')
        return 2
    目标 = os.path.abspath(参数[0])
    os.makedirs(目标, exist_ok=True)
    源 = os.path.join(这里, '配置.txt')
    目 = os.path.join(目标, '配置.txt')
    if not os.path.exists(目):
        shutil.copy2(源, 目)
    for d in ('数据', '权重', '脚本', '影像', '图', '报告'):
        os.makedirs(os.path.join(目标, '产物', d), exist_ok=True)
    print('已在 %s 开好一条新管线。' % 目标)
    print('接下来：')
    print('    cd /d "%s"' % 目标)
    print('    python "%s" 全部' % os.path.join(这里, 'run.py'))
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', '帮助'):
        print(__doc__)
        return 0

    动作, 参数 = sys.argv[1], sys.argv[2:]

    if 动作 == '新建':
        return 新建(参数)

    if 动作 == '外推':
        # 换一块没训练过的地，验泛化。ROI 必须显式给。
        if '--roi' not in 参数:
            print('★ 外推要指定一块【没训练过】的地：')
            print('    python run.py 外推 --roi 101.4 25.4 101.6 25.6')
            return 2
        码 = 跑(步骤['下载'], 参数 + ['--标签', '外推'])
        if 码:
            return 码
        return 跑(步骤['解码'], 摘参数(参数, {'--roi'}) + ['--标签', '外推'])

    if 动作 == '全部':
        for 名 in 全部顺序:
            print()
            print('#' * 72)
            print('# %s' % 名)
            print('#' * 72)
            这步 = [] if 名 in 不吃任何 else list(参数)
            码 = 跑(步骤[名], 这步, 串跑=True)
            if 码:
                print()
                print('★ 「%s」失败（退出码 %d），管线中止。' % (名, 码))
                if 名 == '门禁':
                    print('  门禁没过禁止往下走。先修，不要跳过。')
                return 码
        print()
        print('全部跑完。报告在 产物/报告/结果.md')
        return 0

    if 动作 not in 步骤:
        print('不认识的动作 %r' % 动作)
        print('可用： %s  全部  外推  新建' % '  '.join(步骤))
        return 2

    return 跑(步骤[动作], 参数)


if __name__ == '__main__':
    sys.exit(main())
