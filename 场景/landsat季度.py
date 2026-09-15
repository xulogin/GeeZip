# -*- coding: utf-8 -*-
"""场景 · Landsat 四季合成，6 波段 x 4 季度 = 24 维。

★ 这个场景才是 GeeZip 真正的主场。
  时序数据里相邻季节高度相似，冗余比单期影像大得多，压缩收益也大得多：
      landsat年度（6 维 → 3 维）   下载量 ÷ 4.2
      landsat季度（24 维 → 6 维）  下载量 ÷ 8.1

★★★ 本文件与同名 .js 必须【逐行对应】★★★
"""

NAME = 'landsat季度'
说明 = 'Landsat 8/9 四个季度各一张中位数合成，6 波段 x 4 季 = 24 维'

原始波段 = ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7']
基础别名 = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']

# 季度端点。★ JS 侧必须一模一样
季度 = [('01-01', '04-01'), ('04-01', '07-01'),
        ('07-01', '10-01'), ('10-01', '12-31')]

FEATURES = ['q%d_%s' % (i + 1, b)
            for i in range(len(季度)) for b in 基础别名]

DEFAULT_ROI = [102.6, 24.9, 102.8, 25.1]
DEFAULT_YEAR = 2023
SCALE = 30
JS = 'landsat季度.js'

# 出图用生长季那一期的真彩色
RGB = ('q2_red', 'q2_green', 'q2_blue')

缩放 = 0.0000275
偏移 = -0.2

CAVEAT = [
    '季相物候是【地域性】的 —— 用昆明训的编码器搬到别的气候区会明显退化，'
    '实测 RMSE 会翻一倍多。要跨区用就得把多个区域的样本混进训练集。',
    '雨季（Q3）云多，可用观测比其他季度少一半，该季度更依赖年度中位数兜底。',
    '某季度完全没有干净观测的像元会用年度中位数填 —— 那些像元的"季相信息"是假的。',
]


def 去云并缩放(ee, img):
    """与 landsat年度 完全相同的去云和缩放逻辑。"""
    sr = img.select(原始波段).multiply(缩放).add(偏移)
    qa = img.select('QA_PIXEL')
    晴 = (qa.bitwiseAnd(1 << 3).eq(0)
          .And(qa.bitwiseAnd(1 << 4).eq(0))
          .And(qa.bitwiseAnd(1 << 1).eq(0)))
    合法 = sr.reduce(ee.Reducer.min()).gte(0).And(
        sr.reduce(ee.Reducer.max()).lte(1))
    出 = sr.updateMask(晴).updateMask(合法).rename(基础别名)
    # ★ 见 landsat年度.py 的同名函数：不 copyProperties 会让四个季度全空
    return ee.Image(出.copyProperties(img, ['system:time_start']))


def 集合(ee, roi, 年):
    return (ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
            .merge(ee.ImageCollection('LANDSAT/LC08/C02/T1_L2'))
            .filterBounds(roi)
            .filterDate('%d-01-01' % 年, '%d-12-31' % 年))


def build_stack(ee, roi, 年):
    """24 波段：4 个季度各 6 个。

    ★ 某季度没有干净观测的像元用年度中位数兜底 —— 必须兜，
      否则隐层影像会有空洞，下载下来解不了码。
      兜法两边必须完全一致，否则特征指纹立刻不对。
    """
    col = 集合(ee, roi, 年).map(lambda im: 去云并缩放(ee, im))
    年度 = col.median().rename(基础别名)

    出 = []
    for qi, (起, 止) in enumerate(季度):
        季 = col.filterDate('%d-%s' % (年, 起), '%d-%s' % (年, 止)).median()
        季 = ee.Image(季).rename(基础别名).unmask(年度, False)
        出.append(季.select(基础别名).rename(
            ['q%d_%s' % (qi + 1, b) for b in 基础别名]))

    # 全年都没观测的像元填 0，保证无空洞
    return ee.Image.cat(出).select(FEATURES).unmask(0).toFloat()


def sanity(np, X, cols):
    出 = []

    def 列(名):
        return X[:, cols.index(名)] if 名 in cols else None

    出.append(('反射率全部落在 [0,1]',
               bool((X >= -0.01).all() and (X <= 1.01).all())))

    # 每个季度内部，近红外都该高于红波段
    for qi in range(len(季度)):
        近, 红 = 列('q%d_nir' % (qi + 1)), 列('q%d_red' % (qi + 1))
        if 近 is None or 红 is None:
            continue
        出.append(('Q%d 近红外 %.4f > 红 %.4f' % (qi + 1, 近.mean(), 红.mean()),
                   bool(近.mean() > 红.mean())))

    # ★ 关键检查：季相到底有没有信号。
    #   四个季度的 NDVI 如果完全一样，说明兜底把季相抹平了 ——
    #   那这个场景就退化成了 landsat年度，白花 4 倍的取数成本。
    nd = []
    for qi in range(len(季度)):
        近, 红 = 列('q%d_nir' % (qi + 1)), 列('q%d_red' % (qi + 1))
        if 近 is not None and 红 is not None:
            nd.append(float(((近 - 红) / np.maximum(近 + 红, 1e-6)).mean()))
    if len(nd) == len(季度):
        跨度 = max(nd) - min(nd)
        出.append(('四季 NDVI 均值 %s，跨度 %.3f（太小说明季相被兜底抹平了）'
                   % ([round(v, 3) for v in nd], 跨度), bool(跨度 > 0.02)))

    # 相邻季度应该高度相关 —— 这正是时序能压的原因
    a, b = 列('q1_nir'), 列('q2_nir')
    if a is not None and b is not None:
        r = float(np.corrcoef(a, b)[0, 1])
        出.append(('相邻季度近红外相关 %.3f（时序冗余，能压的根据）' % r,
                   bool(r > 0.5)))

    return 出
