# -*- coding: utf-8 -*-
"""场景模板 —— 复制这份改成你自己的。

    copy _新场景模板.py  我的场景.py
    copy _新场景模板.js  我的场景.js
    然后把 配置.txt 的 scene 改成 我的场景

★★ 最重要的一条 ★★
  这个文件是场景的【Python 半边】，同名 .js 是【JS 半边】。
  两边的特征栈必须逐行对应，改了一边一定要改另一边。
  第一道核对（一致性）抓不到这种漂移，只有【特征指纹】抓得到。

★ 换场景通常只改三处：
  1. build_stack()   特征栈（.py 和 .js 都要改）
  2. FEATURES        波段名和顺序，两边必须一致
  3. sanity()        领域常识检查（千万别省）

引擎、核对、权重存取、组装流程一行都不用动。
"""

NAME = '_新场景模板'
说明 = '（一句话说清这个场景是什么数据）'

FEATURES = ['b1', 'b2', 'b3']          # ← 改成你的波段名和顺序

DEFAULT_ROI = [102.6, 24.9, 102.8, 25.1]
DEFAULT_YEAR = 2023
SCALE = 30                              # 米
JS = '_新场景模板.js'                    # JS 半边文件名，改名时同步改

RGB = ('b3', 'b2', 'b1')                # 出图用哪三个波段做真彩色

# 这个场景已知的系统性问题。
# ★ 写不出来说明你还没搞清楚这份数据有什么毛病，那才是最危险的状态。
CAVEAT = [
    '（把已知偏差写在这里，让每次跑都提醒自己）',
]


def build_stack(ee, roi, 年):
    """返回特征影像。波段名和顺序必须正好是 FEATURES。

    ★ 必须与同名 .js 的 FS.build() 逐行对应。

    ★ 如果你用了 multiply / add 这类运算，记得 copyProperties：
        return ee.Image(出.copyProperties(img, ['system:time_start']))
      不加的话属性全丢，后面 filterDate 在 map 过的集合上一个都筛不到，
      而 GEE 只会在下游报 "Image with no bands"，报错位置离真 bug 很远。

    ★ 结果里不能有空洞（掩膜像元）。有空洞的话隐层下载下来解不了码。
      该兜底就兜底，但兜法两边必须完全一致。
    """
    col = (ee.ImageCollection('你的/数据集')
           .filterBounds(roi)
           .filterDate('%d-01-01' % 年, '%d-12-31' % 年))
    return col.median().select(FEATURES).toFloat()


def sanity(np, X, cols):
    """领域常识检查。返回 [(说明, 通过与否)]，用 None 表示"只报不判"。

    X 形状 (N, D)，cols 就是 FEATURES。

    ★ 这里写的是【领域常识】不是统计检验：符号错了就是错了，
      不管 p 值多好看。这一节救过命。

    ★ 至少写两条：
      1. 取值落在物理上合理的范围内
      2. 两个波段之间的关系符合常识（比如植被的近红外应该高于红光）
    """
    出 = []

    def 列(名):
        return X[:, cols.index(名)] if 名 in cols else None

    出.append(('取值全部落在 [0,1]',
               bool((X >= -0.01).all() and (X <= 1.01).all())))

    # ← 换成你有把握的那条常识
    a, b = 列(FEATURES[0]), 列(FEATURES[1])
    if a is not None and b is not None:
        r = float(np.corrcoef(a, b)[0, 1])
        出.append(('%s 与 %s 相关 %.3f（相关度高才有得压）'
                   % (FEATURES[0], FEATURES[1], r), None))

    return 出
