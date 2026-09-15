# -*- coding: utf-8 -*-
"""配置读取 + 路径 + EE 初始化 + 场景加载。

★ 单一真源：任何一个数字在别处出现第二遍，都是 bug 的温床。
"""
import os
import sys
import importlib.util

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

默认 = dict(
    project='自动', geelo='auto', scene='landsat年度',
    k=3, 量化位数=8,
    样本数=60000, 轮数=400, 批大小=512, 学习率=0.003,
    验证占比=0.2, 随机种子=2026,
    一致性阈值=1e-5, 指纹阈值=1e-6,
    噪声地板=0.005, 最大分块=4,
)

整数键 = {'k', '量化位数', '样本数', '轮数', '批大小', '随机种子', '最大分块'}
浮点键 = {'学习率', '验证占比', '一致性阈值', '指纹阈值', '噪声地板'}


def _读文本(p):
    """配置文件按 UTF-8 读；读不了再退回 GBK。

    ★ 为什么要兜底：中文 Windows 上用记事本另存很容易存成 ANSI(GBK)。
      直接 open(encoding='utf-8') 会抛 UnicodeDecodeError，
      而报错信息完全看不出是编码问题。
    """
    for enc in ('utf-8-sig', 'utf-8', 'gbk'):
        try:
            with open(p, encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, LookupError):
            continue
    raise SystemExit('★ 读不了 %s —— 编码既不是 UTF-8 也不是 GBK。' % p)


_缓存 = None


def load(重读=False):
    global _缓存
    if _缓存 is not None and not 重读:
        return _缓存

    cfg = dict(默认)
    p = os.path.join(根, '配置.txt')
    if os.path.exists(p):
        for 行 in _读文本(p).splitlines():
            行 = 行.strip()
            if not 行 or 行.startswith('#') or '=' not in 行:
                continue
            k, v = 行.split('=', 1)
            k, v = k.strip(), v.split('#')[0].strip()
            if not k:
                continue
            if k in 整数键:
                try:
                    v = int(float(v))
                except ValueError:
                    continue
            elif k in 浮点键:
                try:
                    v = float(v)
                except ValueError:
                    continue
            cfg[k] = v

    cfg['_root'] = 根
    _缓存 = cfg
    return cfg


def paths(工作目录=None):
    """产物目录。默认落在【当前工作目录】，不污染插件本体。"""
    基 = 工作目录 or os.getcwd()
    出 = os.path.join(基, '产物')
    d = dict(
        工作=基, 产物=出,
        数据=os.path.join(出, '数据'),
        权重=os.path.join(出, '权重'),
        脚本=os.path.join(出, '脚本'),
        影像=os.path.join(出, '影像'),
        图=os.path.join(出, '图'),
        报告=os.path.join(出, '报告'),
    )
    for k, v in d.items():
        if k != '工作':
            os.makedirs(v, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
def 项目ID(cfg=None):
    """环境变量 EE_PROJECT 优先，其次 配置.txt。"""
    cfg = cfg or load()
    env = os.environ.get('EE_PROJECT', '').strip()
    if env:
        return env, '环境变量 EE_PROJECT'
    v = str(cfg.get('project', '')).strip()
    if v and v not in ('自动', 'auto', '你的项目ID', ''):
        return v, '配置.txt'
    return None, None


def init_ee(cfg=None):
    """初始化 Earth Engine。代理没开会直接 TIMEOUT，这里给出人话提示。"""
    cfg = cfg or load()
    pid, 来源 = 项目ID(cfg)
    if not pid:
        sys.exit(
            '★ 还不知道你的 Earth Engine 项目 ID。\n'
            '  跑一次这个，它会自动开浏览器、写好凭据、并设好 EE_PROJECT：\n'
            '      node "<GeeLo>/测试台/认证.js"\n'
            '  （<GeeLo> 的位置见 python run.py 自检）')
    try:
        import ee
    except ImportError:
        sys.exit('★ 没装 earthengine-api：\n'
                 '      pip install -r "%s"' % os.path.join(根, 'requirements.txt'))
    try:
        ee.Initialize(project=pid)
    except Exception as e:
        s = str(e)
        提示 = ''
        if 'TIMEOUT' in s.upper() or 'timed out' in s or 'ETIMEDOUT' in s:
            提示 = ('\n  多半是网络：确认你的代理软件正在跑，'
                    '并且 HTTPS_PROXY 环境变量指向它。')
        sys.exit('★ Earth Engine 初始化失败（项目 %s，来自%s）：\n  %s%s'
                 % (pid, 来源, s, 提示))
    return ee


# ---------------------------------------------------------------------------
def 解析(ap, argv=None):
    """参数解析。

    ★ 串跑（run.py 全部）时用 parse_known_args，忽略本步不认识的参数 ——
      因为 `--npix` 是取数的、`--k扫` 是训练的，一条链上必然有互不认识的参数，
      严格解析会在中途 unrecognized arguments 把整条链掐断。

    ★ 单步跑时仍然【严格】解析 —— 否则 `--npixx` 这种手滑会被静默吞掉，
      用户还以为生效了。
    """
    if os.environ.get('GEEZIP_CHAIN') == '1':
        a, 剩 = ap.parse_known_args(argv)
        if 剩:
            print('  （本步忽略了不属于它的参数：%s）' % ' '.join(剩))
        return a
    return ap.parse_args(argv)


def 场景目录():
    return os.path.join(根, '场景')


def 列出场景():
    d = 场景目录()
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d)
                  if f.endswith('.py') and not f.startswith('_'))


def load_scene(cfg=None, 名=None):
    """加载场景模块。场景定义"输入特征栈长什么样"。"""
    cfg = cfg or load()
    名 = 名 or cfg.get('scene', 'landsat年度')
    p = os.path.join(场景目录(), '%s.py' % 名)
    if not os.path.exists(p):
        sys.exit('★ 找不到场景 %r（%s）\n  现有场景：%s\n'
                 '  换场景改 配置.txt 的 scene，或加 --scene'
                 % (名, p, '、'.join(列出场景()) or '（一个都没有）'))
    spec = importlib.util.spec_from_file_location('场景_' + 名, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    for 必须 in ('NAME', 'FEATURES', 'JS', 'build_stack'):
        if not hasattr(m, 必须):
            sys.exit('★ 场景 %s 缺少 %s。照着 场景/_新场景模板.py 补。' % (名, 必须))
    jsp = os.path.join(场景目录(), m.JS)
    if not os.path.exists(jsp):
        sys.exit('★ 场景 %s 的 JS 半边不存在：%s\n'
                 '  特征栈必须两边各写一遍，否则第二道门禁没法比。' % (名, jsp))
    m._py = p
    m._js = jsp
    return m
