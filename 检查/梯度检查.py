# -*- coding: utf-8 -*-
"""数值梯度检查 —— 手写反向传播的唯一保险。

    python 检查/梯度检查.py

★ 为什么这个文件必须存在：
  反向传播写错了【不会报错】。它照样收敛，照样给出看着合理的 RMSE，
  只是收敛到别的地方。本项目实际抓到过一次：
      损失是 ((y-x)**2).mean()，除的是 N*D 个元素，
      反向却只除了 N —— 梯度整体大了 D 倍。
      表现出来只是"学习率不太对"，静态审读绝对看不出来。
  数值梯度检查一眼就抓住了：相对误差恒为 (D-1)/D = 0.8333。

★ ReLU 的假阳性：
  ReLU 在 0 处不可导。预激活贴着 0 的元素，数值梯度会把开关翻一次，
  算出来的值没有意义。本检查因此【用 tanh 做判定】——
  处处可导，没有假阳性。ReLU 那一轮只作参考，不作判据。
"""
import sys
import os

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '引擎'))
import numpy as np
import 自编码器 as M
from 自编码器 import 自编码器


def 检查(用tanh, D=6, k=3, N=17, 隐层=(8, 5), eps=1e-6, 抽=8):
    原r, 原rd = M.relu, M.relu导
    if 用tanh:
        M.relu = np.tanh
        M.relu导 = lambda u: 1.0 - np.tanh(u) ** 2
    try:
        rng = np.random.default_rng(0)
        X = rng.uniform(0.02, 0.5, size=(D, N))
        ae = 自编码器(D, k, 隐层=隐层, 位数=8, 种子=1)
        ae.xMu = X.mean(1, keepdims=True)
        ae.xSd = X.std(1, keepdims=True) + 1e-8

        def 损失():
            y, _ = ae.前向(X, 量化开=False)      # 量化是阶梯函数，数值梯度无意义
            return float(((y - X) ** 2).mean())

        c = {}
        y, _ = ae.前向(X, 量化开=False, 缓存=c)
        G = ae.反向(X, y, c)
        P = ae.参数()
        名 = (['eW%d' % i for i in range(len(ae.eW))] +
              ['eb%d' % i for i in range(len(ae.eb))] +
              ['dW%d' % i for i in range(len(ae.dW))] +
              ['db%d' % i for i in range(len(ae.db))])

        最差 = 0.0
        行 = []
        for nm, p, g in zip(名, P, G):
            e = 0.0
            for f in range(min(抽, p.size)):
                i0 = np.unravel_index(f, p.shape)
                old = p[i0]
                p[i0] = old + eps; l1 = 损失()
                p[i0] = old - eps; l2 = 损失()
                p[i0] = old
                num = (l1 - l2) / (2 * eps)
                e = max(e, abs(num - g[i0]) / max(abs(num), abs(g[i0]), 1e-12))
            最差 = max(最差, e)
            行.append((nm, p.shape, e))
        return 最差, 行
    finally:
        M.relu, M.relu导 = 原r, 原rd


def main():
    print('=' * 70)
    print('参考轮：ReLU（会有拐点假阳性，不作判据）')
    print('=' * 70)
    e1, 行1 = 检查(用tanh=False)
    for nm, sh, e in 行1:
        print('  %-6s %-10s  %.3e  %s' % (nm, str(sh), e, '' if e < 1e-5 else '(拐点?)'))
    print('  最差 %.3e' % e1)

    print()
    print('=' * 70)
    print('★ 判定轮：tanh（处处可导，无假阳性）')
    print('=' * 70)
    e2, 行2 = 检查(用tanh=True)
    for nm, sh, e in 行2:
        print('  %-6s %-10s  %.3e  %s' % (nm, str(sh), e, 'OK' if e < 1e-5 else '★ 不对'))
    print()

    # 量化往返
    ae = 自编码器(6, 3, 隐层=(8, 5), 位数=8)
    rng = np.random.default_rng(3)
    z = rng.uniform(-1, 1, size=(3, 50))
    q = ae.量化(z); zd = ae.反量化(q)
    往返 = float(np.abs(zd - z).max())
    步长 = 1.0 / ae.L
    print('  量化取值范围 [%.0f, %.0f]（应在 [0,%d]）' % (q.min(), q.max(), ae.L))
    print('  往返最大误差 %.6f（应 <= %.6f = 半步长的量级）' % (往返, 步长))
    print('  STE 前向确实量化  %s' % np.allclose(ae.量化直通(z), zd))

    ok = (e2 < 1e-5) and (往返 <= 步长) and np.allclose(ae.量化直通(z), zd)
    print()
    print('=' * 70)
    print('GRAD_CHECK %s   最差相对误差 %.3e' % ('PASS' if ok else 'FAIL', e2))
    print('=' * 70)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
