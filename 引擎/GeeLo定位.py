# -*- coding: utf-8 -*-
"""
找 GeeLo —— 本管线唯一的外部依赖。

★ 为什么 GeeZip 不自带一份 GeeLo：
  自带过。那份副本在仓库里躺了两个月，GeeLo 那边加了 认证.js、
  换了代理探测，自带的这份一样都没有 —— 而且没有任何机制会告诉你它旧了。
  副本 + 无同步机制 = 早晚变成一份骗人的东西。
  所以现在只依赖、不复制：GeeLo 在哪由这个文件负责找出来。

判据只有一条：**目录下有没有 `测试台/跑GEE.js`**。
不看目录叫什么名字，不看版本号 —— 只看那个文件在不在。

找的顺序（先到先得）：
  1. 配置.txt 的  geelo = <绝对路径>
  2. 环境变量    GEELO_HOME
  3. Claude Code 已装插件（读 installed_plugins.json，认 geelo@任意市场）
  4. Claude Code 的市场克隆（marketplaces/*/）
  5. Codex 已装插件
  6. %LOCALAPPDATA%\\GeeZip\\GeeLo       <- 装GeeLo.js 装到这里
     %LOCALAPPDATA%\\GeeDL\\GeeLo        <- 装过 GeeDL 的人已经有一份，直接用
  7. 本管线的相邻目录 ./GeeLo、../GeeLo   <- 手动 clone 的人
"""

import io
import json
import os

# 判据文件。改这个常量之前想清楚：它是"是不是 GeeLo"的唯一定义。
标志文件 = os.path.join('测试台', '跑GEE.js')

HOME = os.path.expanduser('~')


def _有GeeLo(d):
    return bool(d) and os.path.exists(os.path.join(d, 标志文件))


def _claude插件():
    """
    Claude Code 装的插件。

    ★ 认 `geelo@任意市场名`，不是只认 `geelo@geelo`。
      因为 GeeDL 自己的市场里也挂了 GeeLo，从那儿装的话
      键名是 `geelo@geedl` —— 只认 geelo@geelo 会找不到自己推荐的装法。
    """
    出 = []
    f = os.path.join(HOME, '.claude', 'plugins', 'installed_plugins.json')
    try:
        with io.open(f, encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    for 键, 装法 in (data.get('plugins') or {}).items():
        if not 键.split('@')[0].lower() == 'geelo':
            continue
        for one in (装法 if isinstance(装法, list) else [装法]):
            p = (one or {}).get('installPath')
            if p:
                出.append(p)

    # 市场克隆本身也是一份完整的 GeeLo 仓库（marketplace add 会 git clone 全库）。
    # 插件装失败、但市场加成功的情况下，这是唯一还能用的一份。
    市场 = os.path.join(HOME, '.claude', 'plugins', 'marketplaces')
    try:
        for name in os.listdir(市场):
            出.append(os.path.join(市场, name))
    except Exception:
        pass
    return 出


def _codex插件():
    """Codex 的插件目录。层级不像 Claude 那样有清单文件可读，只能有限深度扫。"""
    出 = []
    根 = os.path.join(HOME, '.codex', 'plugins')
    if not os.path.isdir(根):
        return 出
    for 深度, (dirpath, dirnames, _) in enumerate(os.walk(根)):
        # 只扫 4 层，别在别人机器上把整个 .codex 遍历一遍
        if dirpath[len(根):].count(os.sep) >= 4:
            dirnames[:] = []
            continue
        if _有GeeLo(dirpath):
            出.append(dirpath)
            dirnames[:] = []          # 找到了就不再往里钻
    return 出


def 找(显式=None, 管线根=None):
    """
    返回 GeeLo 根目录的绝对路径；找不到返回 None。

    显式：配置.txt 里写死的路径（写了就优先，但仍然要通过判据校验 ——
          路径写错了要当场报"没找到"，不能装作找到了然后在别处炸）。
    """
    候选 = []
    if 显式:
        候选.append(显式)
    if os.environ.get('GEELO_HOME'):
        候选.append(os.environ['GEELO_HOME'])
    候选 += _claude插件()
    候选 += _codex插件()

    本地 = os.environ.get('LOCALAPPDATA') or os.path.join(HOME, 'AppData', 'Local')
    # ★ GeeDL 的位置也要找：装过 GeeDL 的人机器上已经有一份装好依赖的 GeeLo，
    #   没道理让他再下 104 MB。
    候选.append(os.path.join(本地, 'GeeZip', 'GeeLo'))
    候选.append(os.path.join(本地, 'GeeDL', 'GeeLo'))

    if 管线根:
        候选.append(os.path.join(管线根, 'GeeLo'))
        候选.append(os.path.join(os.path.dirname(管线根), 'GeeLo'))

    # ★ 两轮：先挑**依赖装好了的**，再退而求其次。
    #   否则会出现这种事：插件目录里有一份 GeeLo 但没 npm install（插件本来就
    #   不带 node_modules），而 %LOCALAPPDATA% 下另有一份装好能跑的 ——
    #   按顺序取第一个会选中前者，然后报"缺 node_modules"，
    #   而用户明明已经装好了。选能用的那份，比选排在前面的那份重要。
    for 要求依赖 in (True, False):
        for d in 候选:
            if _有GeeLo(d) and (装好了吗(d) if 要求依赖 else True):
                return os.path.abspath(d)
    return None


def 跑GEE(geelo):
    return os.path.join(geelo, '测试台', '跑GEE.js') if geelo else None


def 一键开GEE(geelo):
    p = os.path.join(geelo, '送进编辑器', 'gee-open.js') if geelo else None
    return p if p and os.path.exists(p) else None


def 装好了吗(geelo):
    """GeeLo 的测试台依赖装了没有（约 104 MB，不进版本库，要 npm install）。"""
    return bool(geelo) and os.path.isdir(
        os.path.join(geelo, '测试台', 'node_modules'))


# ---------------------------------------------------------------------------
# 找不到时说什么。**只在这里写一次**，让所有调用点报一样的话 ——
# 报错文案分散在各处，改一处漏三处，用户看到的提示互相矛盾。
def 没找到怎么办(管线根):
    装脚本 = os.path.join(管线根 or '.', '装GeeLo.js')
    return (
        '★ 没找到 GeeLo。它提供本管线的实跑测试台（门禁和出图都要用）。\n'
        '\n'
        '  最省事：跑这一条，它自己 clone + npm install\n'
        '      node "%s"\n'
        '\n'
        '  已经用插件装过 GeeLo 的，多半是终端没重开或装到了别处，\n'
        '  可以直接指路：在 配置.txt 写 geelo = <GeeLo 的绝对路径>\n'
        '\n'
        '  什么是 GeeLo：https://github.com/xulogin/GeeLo' % 装脚本)


def 依赖没装怎么办(geelo):
    return (
        '★ 找到 GeeLo 了（%s），但它的测试台依赖没装（缺 node_modules，约 104 MB）。\n'
        '  跑这一条：\n'
        '      cd /d "%s" && npm install' % (geelo, os.path.join(geelo, '测试台')))
