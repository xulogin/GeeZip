# -*- coding: utf-8 -*-
"""自检 —— 换电脑第一件事。

    python run.py 自检

逐项报，每项失败都给出"怎么办"。全绿才开工。
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import 配置 as CFG                                    # noqa: E402
import GeeLo定位                                      # noqa: E402

好 = 0
坏 = 0
待办 = []


def 报(名, ok, 值='', 怎么办=''):
    global 好, 坏
    if ok:
        好 += 1
        print('  OK   %-26s %s' % (名, 值))
    else:
        坏 += 1
        print('  X    %-26s %s' % (名, 值))
        if 怎么办:
            print('       -> %s' % 怎么办)
            待办.append((名, 怎么办))


def main(argv=None):
    cfg = CFG.load()
    根 = cfg['_root']

    print('=' * 72)
    print('GeeZip · 环境自检')
    print('  插件目录 %s' % 根)
    print('  工作目录 %s' % os.getcwd())
    print('=' * 72)

    # --- Python 和包 ---------------------------------------------------
    报('Python', sys.version_info >= (3, 8),
      '.'.join(map(str, sys.version_info[:3])),
      '需要 3.8 以上')

    缺包 = []
    for 模块, 装名 in (('numpy', 'numpy'), ('pandas', 'pandas'),
                      ('sklearn', 'scikit-learn'), ('rasterio', 'rasterio'),
                      ('skimage', 'scikit-image'),
                      ('matplotlib', 'matplotlib'), ('ee', 'earthengine-api')):
        try:
            m = __import__(模块)
            报('模块 ' + 模块, True, getattr(m, '__version__', ''))
        except ImportError:
            缺包.append(装名)
            报('模块 ' + 模块, False, '没装',
              'pip install -r "%s"' % os.path.join(根, 'requirements.txt'))

    # --- 配置和场景 -----------------------------------------------------
    报('配置.txt', os.path.exists(os.path.join(根, '配置.txt')),
      'scene = %s   k = %s' % (cfg.get('scene'), cfg.get('k')))

    try:
        scene = CFG.load_scene(cfg)
        报('场景 ' + str(cfg.get('scene')), True,
          '%d 维输入，JS 半边在位' % len(scene.FEATURES))
    except SystemExit as e:
        scene = None
        报('场景 ' + str(cfg.get('scene')), False, str(e)[:60],
          '配置.txt 的 scene 写错了？现有：%s' % '、'.join(CFG.列出场景()))

    # --- GeeLo ----------------------------------------------------------
    显式 = cfg.get('geelo')
    显式 = None if str(显式).strip() in ('auto', '', '自动') else 显式
    geelo = GeeLo定位.找(显式, 根)
    if not geelo:
        报('GeeLo', False, '没找到',
          'node "%s"' % os.path.join(根, '装GeeLo.js'))
    else:
        报('GeeLo', True, geelo)
        报('GeeLo 测试台依赖', GeeLo定位.装好了吗(geelo),
          '已装' if GeeLo定位.装好了吗(geelo) else '缺 node_modules',
          'cd /d "%s" && npm install' % os.path.join(geelo, '测试台'))

    # --- Node -----------------------------------------------------------
    try:
        r = subprocess.run(['node', '--version'], capture_output=True)
        v = (r.stdout or b'').decode('utf-8', 'replace').strip()
        主 = int(v.lstrip('v').split('.')[0]) if v.startswith('v') else 0
        报('Node.js', 主 >= 20, v or '?', '需要 20.19 以上')
    except FileNotFoundError:
        报('Node.js', False, '没装', '装 Node.js 20 LTS 以上')

    # --- EE 项目和凭据 ---------------------------------------------------
    pid, 来源 = CFG.项目ID(cfg)
    报('EE 项目 ID', bool(pid), '%s（%s）' % (pid, 来源) if pid else '没配',
      'node "%s"' % os.path.join(geelo or '<GeeLo>', '测试台', '认证.js'))

    凭据 = os.path.join(os.path.expanduser('~'), '.config',
                       'earthengine', 'credentials')
    报('EE 凭据', os.path.exists(凭据),
      '已存在' if os.path.exists(凭据) else '没有',
      'node "%s"' % os.path.join(geelo or '<GeeLo>', '测试台', '认证.js'))

    代理 = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    报('代理', True, 代理 or '（没设环境变量，直连）')

    # --- 真连一次 --------------------------------------------------------
    if pid and os.path.exists(凭据) and not 缺包:
        try:
            import ee
            ee.Initialize(project=pid)
            v = ee.Number(1).add(1).getInfo()
            报('连接 Earth Engine', v == 2, '1 + 1 = %s' % v)
        except Exception as e:
            s = str(e)[:70]
            提示 = '确认代理软件在跑' if ('TIMEOUT' in str(e).upper()
                                      or 'ETIMEDOUT' in str(e)) else '看上面的错'
            报('连接 Earth Engine', False, s, 提示)
    else:
        报('连接 Earth Engine', False, '跳过（前面有项没过）',
          '把上面标 X 的解决后重跑')

    # --- 总结 ------------------------------------------------------------
    print()
    print('=' * 72)
    print('  自检结果：通过 %d 项，失败 %d 项' % (好, 坏))
    print('=' * 72)
    if 坏:
        print()
        print('  待办（按顺序处理，前面解决了后面可能自动好）：')
        for i, (名, 法) in enumerate(待办, 1):
            print('    %d. %s' % (i, 法))
        return 1

    print()
    print('  一切就绪。下一步：python run.py 全部')
    return 0


if __name__ == '__main__':
    sys.exit(main())
