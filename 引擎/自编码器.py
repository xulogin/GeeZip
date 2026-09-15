# -*- coding: utf-8 -*-
"""量化感知的编码器—解码器，纯 numpy 实现。

为什么不用 torch：
  - 本机 Anaconda 3.8 没有 torch，GeeDL 也证明了 numpy 够用
  - 这个网络小到不值得上框架（编码器约 500~2500 参数）
  - 更重要的：手写前向 = 我完全知道每一步在算什么，
    才能一行一行翻译成 GEE 的 JS，两边才对得上

结构：
    编码器（→ GEE）  D → h1 → h2 → k     relu, relu, tanh
    量化            uint8，直通估计器反传
    解码器（留本地）  k → h2 → h1 → D     relu, relu, linear

★ 为什么编码器最后一层是 tanh：
  把隐层收进 [-1,1]，量化区间才是【固定】的。
  不收口的话隐层范围随数据漂，uint8 的映射系数就没法写死进 GEE 脚本，
  换一块地跑出来的隐层就解不开了。

★ 为什么要量化感知训练：
  隐层最终要以 uint8 下载。训练时不量化、下载时才量化，
  等于训练和部署用的是两个不同的模型 —— 精度会无声无息掉一截。
"""
import numpy as np


# ---------------------------------------------------------------------------
# 基本件
# ---------------------------------------------------------------------------
def he初始化(n入, n出, rng):
    return rng.normal(0, np.sqrt(2.0 / n入), size=(n出, n入))


def relu(u):
    return np.maximum(u, 0.0)


def relu导(u):
    return (u > 0).astype(u.dtype)


def tanh导(y):
    """y 是 tanh 的输出。"""
    return 1.0 - y * y


class 自编码器(object):

    def __init__(self, D, k, 隐层=(24, 12), 位数=8, 种子=2026):
        rng = np.random.default_rng(种子)
        self.D, self.k, self.位数 = D, k, 位数
        self.L = (1 << 位数) - 1                      # uint8 → 255

        enc = [D] + list(隐层) + [k]
        dec = [k] + list(隐层)[::-1] + [D]
        self.enc尺寸, self.dec尺寸 = enc, dec

        self.eW = [he初始化(enc[i], enc[i + 1], rng) for i in range(len(enc) - 1)]
        self.eb = [np.zeros((enc[i + 1], 1)) for i in range(len(enc) - 1)]
        self.dW = [he初始化(dec[i], dec[i + 1], rng) for i in range(len(dec) - 1)]
        self.db = [np.zeros((dec[i + 1], 1)) for i in range(len(dec) - 1)]

        # 输入标准化参数，训练时从数据估，之后写死进 GEE 脚本
        self.xMu = np.zeros((D, 1))
        self.xSd = np.ones((D, 1))

    # -- 参数打包，给 Adam 用 ------------------------------------------------
    def 参数(self):
        return self.eW + self.eb + self.dW + self.db

    # -----------------------------------------------------------------------
    # 编码。X 形状 (D, N)，返回隐层 z 形状 (k, N)，范围 [-1,1]
    # ★ 这个函数就是要翻译成 GEE JS 的那一段，改它必须同步改 JS
    # -----------------------------------------------------------------------
    def 编码(self, X, 缓存=None):
        h = (X - self.xMu) / self.xSd
        if 缓存 is not None:
            缓存['x_n'] = h
            缓存['e_u'] = []
            缓存['e_h'] = [h]
        for i in range(len(self.eW) - 1):
            u = self.eW[i] @ h + self.eb[i]
            h = relu(u)
            if 缓存 is not None:
                缓存['e_u'].append(u)
                缓存['e_h'].append(h)
        u = self.eW[-1] @ h + self.eb[-1]
        z = np.tanh(u)
        if 缓存 is not None:
            缓存['e_u'].append(u)
            缓存['z'] = z
        return z

    # -----------------------------------------------------------------------
    # 量化 / 反量化。这是压缩真正兑现成字节的地方
    # -----------------------------------------------------------------------
    def 量化(self, z):
        """[-1,1] → 整数 [0, L]。返回的是整数，下载的就是它。"""
        return np.rint((z + 1.0) * 0.5 * self.L)

    def 反量化(self, q):
        return q / self.L * 2.0 - 1.0

    def 量化直通(self, z):
        """前向真量化，反向当恒等（STE）。训练时用这个。"""
        return z + (self.反量化(self.量化(z)) - z)      # 数值上等于 zq

    # -----------------------------------------------------------------------
    # 解码。留在本地，不需要翻译成 JS
    # -----------------------------------------------------------------------
    def 解码(self, z, 缓存=None):
        h = z
        if 缓存 is not None:
            缓存['d_u'] = []
            缓存['d_h'] = [h]
        for i in range(len(self.dW) - 1):
            u = self.dW[i] @ h + self.db[i]
            h = relu(u)
            if 缓存 is not None:
                缓存['d_u'].append(u)
                缓存['d_h'].append(h)
        y = self.dW[-1] @ h + self.db[-1]              # 最后一层线性
        if 缓存 is not None:
            缓存['d_u'].append(y)
        return y

    def 前向(self, X, 量化开=True, 缓存=None):
        z = self.编码(X, 缓存)
        zq = self.量化直通(z) if 量化开 else z
        if 缓存 is not None:
            缓存['zq'] = zq
        return self.解码(zq, 缓存), z

    # -----------------------------------------------------------------------
    # 反向传播。手写，因为要保证我清楚每一步
    # -----------------------------------------------------------------------
    def 反向(self, X, Y预测, 缓存):
        N = X.shape[1]
        # ★ 分母必须是 N*D，不是 N。
        #   损失是 ((y-x)**2).mean()，mean 除的是 N*D 个元素。
        #   只除 N 会让梯度整体放大 D 倍 —— 数值梯度检查一眼抓住
        #   （相对误差恒为 (D-1)/D），但训练时它只表现为"学习率不对"，
        #   照样收敛到某个东西，不报错。这就是为什么必须做梯度检查。
        g = 2.0 * (Y预测 - X) / (N * self.D)             # dL/dy，MSE

        geW = [None] * len(self.eW); geb = [None] * len(self.eb)
        gdW = [None] * len(self.dW); gdb = [None] * len(self.db)

        # --- 解码器 ---
        for i in range(len(self.dW) - 1, -1, -1):
            if i < len(self.dW) - 1:
                g = g * relu导(缓存['d_u'][i])
            gdW[i] = g @ 缓存['d_h'][i].T
            gdb[i] = g.sum(axis=1, keepdims=True)
            g = self.dW[i].T @ g

        # --- 量化层：STE，梯度原样透传 ---

        # --- 编码器 ---
        g = g * tanh导(缓存['z'])                       # 先过 tanh
        for i in range(len(self.eW) - 1, -1, -1):
            if i < len(self.eW) - 1:
                g = g * relu导(缓存['e_u'][i])
            geW[i] = g @ 缓存['e_h'][i].T
            geb[i] = g.sum(axis=1, keepdims=True)
            g = self.eW[i].T @ g

        return geW + geb + gdW + gdb

    # -----------------------------------------------------------------------
    # 训练
    # -----------------------------------------------------------------------
    def 训练(self, X训, X验, 轮数=400, 批=512, 学习率=3e-3,
             种子=2026, 打印=None):
        """X 形状 (D, N)，值就是反射率，损失直接是反射率单位的 MSE。"""
        rng = np.random.default_rng(种子)
        self.xMu = X训.mean(axis=1, keepdims=True)
        self.xSd = X训.std(axis=1, keepdims=True) + 1e-8

        P = self.参数()
        m = [np.zeros_like(p) for p in P]
        v = [np.zeros_like(p) for p in P]
        b1, b2, eps = 0.9, 0.999, 1e-8
        t = 0
        N = X训.shape[1]
        史 = []

        for ep in range(轮数):
            序 = rng.permutation(N)
            for s in range(0, N, 批):
                idx = 序[s:s + 批]
                xb = X训[:, idx]
                缓存 = {}
                y, _ = self.前向(xb, 量化开=True, 缓存=缓存)
                G = self.反向(xb, y, 缓存)
                t += 1
                for j, (p, g) in enumerate(zip(P, G)):
                    m[j] = b1 * m[j] + (1 - b1) * g
                    v[j] = b2 * v[j] + (1 - b2) * g * g
                    mh = m[j] / (1 - b1 ** t)
                    vh = v[j] / (1 - b2 ** t)
                    p -= 学习率 * mh / (np.sqrt(vh) + eps)

            if (ep + 1) % 20 == 0 or ep == 0:
                r训 = self.RMSE(X训); r验 = self.RMSE(X验)
                史.append((ep + 1, r训, r验))
                if 打印:
                    打印('  轮 %4d/%d   训练 RMSE %.6f   验证 RMSE %.6f'
                         % (ep + 1, 轮数, r训, r验))
        return 史

    # -----------------------------------------------------------------------
    def 重建(self, X, 量化开=True):
        y, _ = self.前向(X, 量化开=量化开)
        return y

    def RMSE(self, X, 量化开=True):
        y = self.重建(X, 量化开)
        return float(np.sqrt(((y - X) ** 2).mean()))

    # -----------------------------------------------------------------------
    def 存(self, 路径, 附加=None):
        import json
        d = dict(
            D=self.D, k=self.k, 位数=self.位数, L=self.L,
            enc尺寸=self.enc尺寸, dec尺寸=self.dec尺寸,
            xMu=self.xMu.ravel().tolist(), xSd=self.xSd.ravel().tolist(),
            eW=[w.tolist() for w in self.eW], eb=[b.ravel().tolist() for b in self.eb],
            dW=[w.tolist() for w in self.dW], db=[b.ravel().tolist() for b in self.db],
        )
        if 附加:
            d.update(附加)
        with open(路径, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)

    @staticmethod
    def 读(路径):
        import json
        d = json.load(open(路径, encoding='utf-8'))
        隐 = d['enc尺寸'][1:-1]
        ae = 自编码器(d['D'], d['k'], 隐层=tuple(隐), 位数=d['位数'])
        ae.xMu = np.array(d['xMu']).reshape(-1, 1)
        ae.xSd = np.array(d['xSd']).reshape(-1, 1)
        ae.eW = [np.array(w) for w in d['eW']]
        ae.eb = [np.array(b).reshape(-1, 1) for b in d['eb']]
        ae.dW = [np.array(w) for w in d['dW']]
        ae.db = [np.array(b).reshape(-1, 1) for b in d['db']]
        return ae, d


# ---------------------------------------------------------------------------
# PCA 基线 —— 不许跳过，输了要照实说
# ---------------------------------------------------------------------------
class PCA基线(object):

    def __init__(self, k, 位数=8):
        self.k, self.位数 = k, 位数
        self.L = (1 << 位数) - 1

    def 拟合(self, X):
        """X 形状 (D, N)。"""
        self.mu = X.mean(axis=1, keepdims=True)
        Xc = (X - self.mu).T
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        self.V = Vt[:self.k]                            # (k, D)
        Z = Xc @ self.V.T
        # 量化区间用训练集的范围定死，与 AE 的 tanh 收口地位相同
        self.lo, self.hi = Z.min(axis=0), Z.max(axis=0)
        self.方差占比 = (S ** 2 / (S ** 2).sum())[:self.k]
        return self

    def 编码(self, X):
        return ((X - self.mu).T @ self.V.T).T           # (k, N)

    def 量化(self, Z):
        rng = np.maximum(self.hi - self.lo, 1e-12)[:, None]
        return np.rint((Z - self.lo[:, None]) / rng * self.L)

    def 反量化(self, Q):
        rng = np.maximum(self.hi - self.lo, 1e-12)[:, None]
        return Q / self.L * rng + self.lo[:, None]

    def 重建(self, X, 量化开=True):
        Z = self.编码(X)
        if 量化开:
            Z = self.反量化(self.量化(Z))
        return (Z.T @ self.V).T + self.mu

    def RMSE(self, X, 量化开=True):
        return float(np.sqrt(((self.重建(X, 量化开) - X) ** 2).mean()))
