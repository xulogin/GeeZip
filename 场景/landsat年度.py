# -*- coding: utf-8 -*-
"""场景 · Landsat 年度合成，6 个波段。

最简单的一个，拿来跑通管线。压缩收益约 4 倍。
想要更大的收益用 landsat季度（24 维）。

★★★ 本文件与同名 .js 必须【逐行对应】★★★
改了一边一定要改另一边，然后重跑门禁。
一致性门禁抓不到这种漂移，只有【特征指纹】抓得到。
"""

NAME = 'landsat年度'
说明 = 'Landsat 8/9 年度中位数合成，蓝绿红近红外和两个短波红外'

原始波段 = ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7']
FEATURES = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2']

DEFAULT_ROI = [102.6, 24.9, 102.8, 25.1]      # 昆明，0.2 度见方
DEFAULT_YEAR = 2023
SCALE = 30
JS = 'landsat年度.js'

# 出图用哪三个波段做真彩色
RGB = ('red', 'green', 'blue')

# C2 L2 官方缩放系数：反射率 = DN * 缩放 + 偏移
缩放 = 0.0000275
偏移 = -0.2

# 这个场景已知的系统性问题。★ 写不出来说明你还没搞清楚数据，那才最危险。
CAVEAT = [
    '年度中位数会把物候完全抹平 —— 同一块地春天和秋天的差别在这里看不到。',
    '云掩膜用 QA_PIXEL 的 bit 1/3/4，薄云和云边缘漏检是常态。',
    '水体和阴影的反射率都很低，编码器容易把两者压到相近的位置。',
]


def 去云并缩放(ee, img):
    """QA_PIXEL 位掩膜 + 官方缩放。★ 位号写死，不许改。

    bit 1 = 扩张云   bit 3 = 云   bit 4 = 云影
    """
    sr = img.select(原始波段).multiply(缩放).add(偏移)
    qa = img.select('QA_PIXEL')
    晴 = (qa.bitwiseAnd(1 << 3).eq(0)
          .And(qa.bitwiseAnd(1 << 4).eq(0))
          .And(qa.bitwiseAnd(1 << 1).eq(0)))
    # 反射率理论范围 [0,1]，越界的是坏像元
    合法 = sr.reduce(ee.Reducer.min()).gte(0).And(
        sr.reduce(ee.Reducer.max()).lte(1))
    出 = sr.updateMask(晴).updateMask(合法).rename(FEATURES)

    # ★★ copyProperties 不是可有可无 ★★
    #   multiply/add 会【丢掉】原影像属性，system:time_start 一并没了。
    #   丢了之后 filterDate 在 map 过的集合上一个都筛不到。
    #   GEE 不会说"日期没了"，只在下游报 "Image with no bands" ——
    #   报错位置离真 bug 十万八千里。实测踩过。
    return ee.Image(出.copyProperties(img, ['system:time_start']))


def 集合(ee, roi, 年):
    return (ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
            .merge(ee.ImageCollection('LANDSAT/LC08/C02/T1_L2'))
            .filterBounds(roi)
            .filterDate('%d-01-01' % 年, '%d-12-31' % 年))


def build_stack(ee, roi, 年):
    """返回特征影像。波段名和顺序必须正好是 FEATURES。"""
    col = 集合(ee, roi, 年).map(lambda im: 去云并缩放(ee, im))
    return col.median().rename(FEATURES).select(FEATURES).toFloat()


def sanity(np, X, cols):
    """领域常识检查。返回 [(说明, 通过与否)]，None 表示只报不判。

    ★ 这里写的是【领域常识】不是统计检验。这一节救过命。
    """
    出 = []

    def 列(名):
        return X[:, cols.index(名)] if 名 in cols else None

    蓝, 绿, 红 = 列('blue'), 列('green'), 列('red')
    近, 短1, 短2 = 列('nir'), 列('swir1'), 列('swir2')

    出.append(('反射率全部落在 [0,1]',
               bool((X >= -0.01).all() and (X <= 1.01).all())))

    if 近 is not None and 红 is not None:
        出.append(('近红外均值 %.4f > 红波段均值 %.4f（植被该有的样子）'
                   % (近.mean(), 红.mean()), bool(近.mean() > 红.mean())))
        ndvi = (近 - 红) / np.maximum(近 + 红, 1e-6)
        出.append(('NDVI 均值 %.3f（陆地应在 0~0.9）' % ndvi.mean(),
                   bool(0 < ndvi.mean() < 0.9)))

    if 短1 is not None and 短2 is not None:
        出.append(('SWIR1 均值 %.4f > SWIR2 均值 %.4f' % (短1.mean(), 短2.mean()),
                   bool(短1.mean() > 短2.mean())))

    if 蓝 is not None and 绿 is not None:
        r = float(np.corrcoef(蓝, 绿)[0, 1])
        出.append(('蓝绿相关 %.3f（可见光之间应高度相关，这正是能压的原因）' % r,
                   bool(r > 0.8)))

    return 出
