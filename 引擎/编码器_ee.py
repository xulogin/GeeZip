# -*- coding: utf-8 -*-
"""编码器 · Python-ee 半边（跑在 GEE 服务器上，供下载用）

★ 为什么会有第三份实现？
  numpy 那份用来训练，JS 那份用来贴进 Code Editor，
  而 getDownloadURL 只接受 Python 侧的 ee.Image —— 所以下载这条路
  必须有一份 Python-ee 的编码器。

★ 第三份 = 第三次漂移机会。
  所以本文件是 自编码器.py 的 编码() 和 步骤3 生成的 ENC.encode 的
  【逐行转写】，并且 步骤5 在下载之前会拿同一批测试向量把它验一遍，
  验不过就拒绝下载。

  三份实现两两都对得上，这个方案才算成立。
"""
import numpy as np


def 建模型(ee, d):
    """从权重 JSON 建服务端模型对象。"""
    return dict(
        D=d['D'], k=d['k'], L=d['L'], features=d['列'],
        xMu=ee.Image(ee.Array([[v] for v in d['xMu']])),
        xSd=ee.Image(ee.Array([[v] for v in d['xSd']])),
        W=[ee.Image(ee.Array(w)) for w in d['eW']],
        b=[ee.Image(ee.Array([[v] for v in bb])) for bb in d['eb']],
    )


def tanh(u):
    """与 numpy 端、JS 端同一个公式： (e^{2u}-1)/(e^{2u}+1)

    ★ 不用 Image.tanh()：数组波段上一元算子支持不一致，
      用 exp 组合出来的形式标量和数组影像都能用，三边完全对齐。
    """
    e2 = u.multiply(2).exp()
    return e2.subtract(1).divide(e2.add(1))


def 编码(ee, img, m):
    """逐像元前向传播。对应 自编码器.py 的 编码() 和 JS 的 ENC.encode()。

    Xn = (X - xMu) / xSd
    h  = relu(W_i h + b_i)   重复 L-1 次
    z  = tanh(W_L h + b_L)
    """
    x = img.select(m['features']).toArray().toArray(1)      # (D,1)
    h = x.subtract(m['xMu']).divide(m['xSd'])

    L = len(m['W'])
    for i in range(L - 1):
        h = m['W'][i].matrixMultiply(h).add(m['b'][i]).max(0)
    z = tanh(m['W'][L - 1].matrixMultiply(h).add(m['b'][L - 1]))

    名 = ['z%d' % j for j in range(m['k'])]
    return z.arrayProject([0]).arrayFlatten([名]).toFloat()


def 编码_波段算术(ee, img, ae, 列):
    """★ 同一个编码器，改用【波段算术】表达，不碰数组影像。

    为什么需要这一版（实测，非推测）：
      数组影像版（toArray + matrixMultiply）做逐点预测没问题，
      但要把【整幅栅格物化下载】时会撑爆内存 ——
          数组版 全幅 743x743 @30m  →  HTTP 400 "User memory limit exceeded"
          本  版 同样范围同样尺度    →  OK，1.19 MB，5 秒
      原因是 toArray 给每个像元造了一个数组对象，全幅物化时内存开销巨大。

    MLP 的每个隐单元本质就是一个加权和：
        u_j = sum_i W[j][i] * x_i + b_j
    用普通波段算术就能表达，内存开销和普通波段运算一样。

    ★ 实测两版结果【逐位相同】（全幅最大逐像元差 = 0），
      与 numpy 参考差 1.3e-8。步骤5 每次下载前都会重新对拍。
    """
    h = [img.select([c]).subtract(float(ae.xMu[i, 0]))
              .divide(float(ae.xSd[i, 0]))
         for i, c in enumerate(列)]

    L = len(ae.eW)
    for li in range(L):
        W, b = ae.eW[li], ae.eb[li]
        新 = []
        for j in range(W.shape[0]):
            acc = ee.Image.constant(float(b[j, 0]))
            for i in range(W.shape[1]):
                acc = acc.add(h[i].multiply(float(W[j, i])))
            if li < L - 1:
                acc = acc.max(0)                      # ReLU
            else:
                e2 = acc.multiply(2).exp()            # tanh，与另两边同公式
                acc = e2.subtract(1).divide(e2.add(1))
            新.append(acc)
        h = 新
    return ee.Image.cat([h[j].rename('z%d' % j)
                         for j in range(len(h))]).toFloat()


def 对拍两版(ee, img, ae, 列, m, roi, 尺度=120):
    """数组版 vs 波段算术版，返回最大逐像元差。

    ★ 下载走的是波段算术版，门禁验的是数组版 —— 必须证明两者等价，
      否则门禁验的就不是实际下载用的那份代码。
    """
    a = 编码(ee, img, m)
    b = 编码_波段算术(ee, img, ae, 列)
    d = a.subtract(b).abs().reduce(ee.Reducer.max())
    r = d.reduceRegion(reducer=ee.Reducer.max(), geometry=roi,
                       scale=尺度, maxPixels=int(1e9), tileScale=8).getInfo()
    return float(list(r.values())[0] or 0.0)


def 量化(z, m):
    """q = round((z+1)/2 * L)，与 自编码器.py 的 量化() 完全一致。

    ★ 这一步错了，下载下来的隐层就解不开 —— 而且不会报错。
    """
    return (z.add(1).multiply(0.5).multiply(m['L'])
            .round().clamp(0, m['L']).toUint8())


def 编码批(ee, 行, m):
    """一次矩阵乘算完 N 条向量，返回 (k, N) 拍平的 k*N 波段影像。

    对应 JS 的 ENC.encodeMany。下载前的自检用。
    """
    N = len(行)
    Xt = ee.Image(ee.Array([list(map(float, r)) for r in 行]).matrixTranspose())

    h = (Xt.subtract(m['xMu'].arrayRepeat(1, N))
           .divide(m['xSd'].arrayRepeat(1, N)))
    L = len(m['W'])
    for i in range(L - 1):
        h = (m['W'][i].matrixMultiply(h)
             .add(m['b'][i].arrayRepeat(1, N)).max(0))
    z = tanh(m['W'][L - 1].matrixMultiply(h)
             .add(m['b'][L - 1].arrayRepeat(1, N)))          # (k,N)

    zn = ['z%d' % j for j in range(m['k'])]
    rn = ['r%d' % r for r in range(N)]
    return z.arrayFlatten([zn, rn]).toFloat()


def 自检(ee, 行, z参考, m, 阈值=1e-5, 点=(102.7, 25.0)):
    """把 Python-ee 的编码结果与 numpy 参考对拍。

    返回 (最大绝对差, 是否通过)。
    """
    img = 编码批(ee, 行, m)
    d = img.reduceRegion(reducer=ee.Reducer.first(),
                         geometry=ee.Geometry.Point(list(点)),
                         scale=1000, maxPixels=int(1e9),
                         bestEffort=True).getInfo()
    N = len(行)
    得 = np.array([[d['z%d_r%d' % (j, r)] for r in range(N)]
                   for j in range(m['k'])])                  # (k,N)
    差 = np.abs(得 - np.asarray(z参考).T)
    最大 = float(差.max())
    return 最大, bool(最大 < 阈值)
