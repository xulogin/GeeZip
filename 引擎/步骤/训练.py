# -*- coding: utf-8 -*-
"""训练 —— 编码器和解码器一起训，训练时就按下载用的精度取整。

    python run.py 训练
    python run.py 训练 --k 3
    python run.py 训练 --k扫 1 2 3 4        # 扫一遍看率失真，再决定用哪个 k

★ 量化感知：隐层最终要以 uint8 下载。训练时不量化、下载时才量化，
  等于训练和部署用的是两个模型 —— 精度会无声无息掉一截。

★ 验证集用【空间分块】留出，不是随机划分。遥感数据有强空间自相关，
  随机划分会把同一片地的相邻像元拆到两边，验证误差虚低，换个地方就崩。
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402
import 配置 as CFG                                    # noqa: E402
from 自编码器 import 自编码器, PCA基线                 # noqa: E402


def 说(k, v):
    print('  %-32s %s' % (k, v)); sys.stdout.flush()


def 空间分块划分(df, 验证占比, 块数=6, 种子=2026):
    lon, lat = df['lon'].to_numpy(), df['lat'].to_numpy()
    跨x = max(lon.max() - lon.min(), 1e-12)
    跨y = max(lat.max() - lat.min(), 1e-12)
    gx = np.clip(((lon - lon.min()) / 跨x * 块数).astype(int), 0, 块数 - 1)
    gy = np.clip(((lat - lat.min()) / 跨y * 块数).astype(int), 0, 块数 - 1)
    块 = gy * 块数 + gx
    唯一 = np.unique(块)
    rng = np.random.default_rng(种子)
    rng.shuffle(唯一)
    n验 = max(1, int(round(len(唯一) * 验证占比)))
    验块 = set(唯一[:n验].tolist())
    是验 = np.array([b in 验块 for b in 块])
    return ~是验, 是验, len(唯一), n验


def 指标(X真, X重, 列):
    e = X重 - X真
    rmse = float(np.sqrt((e ** 2).mean()))
    return dict(rmse=rmse, mae=float(np.abs(e).mean()),
                psnr=float(20 * np.log10(1.0 / max(rmse, 1e-12))),
                逐波段=dict(zip(列, [round(float(v), 6)
                                   for v in np.sqrt((e ** 2).mean(axis=1))])))


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 训练')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--k扫', type=int, nargs='+', default=None,
                    help='扫多个 k，出一张率失真表，再决定用哪个')
    ap.add_argument('--轮数', type=int, default=None)
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    p = CFG.paths()
    csv = os.path.join(p['数据'], '%s_样本.csv' % scene.NAME)
    if not os.path.exists(csv):
        sys.exit('找不到 %s\n  先跑：python run.py 取数' % csv)

    meta = json.load(open(csv.replace('.csv', '_meta.json'), encoding='utf-8'))
    列 = meta['列']
    df = pd.read_csv(csv)
    D = len(列)
    ks = a.k扫 or [a.k or int(cfg['k'])]
    轮 = a.轮数 or int(cfg['轮数'])

    print('=' * 72)
    print('训练   场景 %s   %d 维输入' % (scene.NAME, D))
    print('=' * 72)
    说('样本', len(df))

    训, 验, n块, n验块 = 空间分块划分(df, float(cfg['验证占比']),
                                   种子=int(cfg['随机种子']))
    说('空间分块', '%d 块，其中 %d 块留作验证' % (n块, n验块))
    说('训练 / 验证', '%d / %d' % (训.sum(), 验.sum()))
    if 验.sum() < 500:
        print('  ★ 验证样本太少，结论不稳。')

    X = df[列].to_numpy(dtype=np.float64).T
    X训, X验 = X[:, 训], X[:, 验]

    # 参照：不降维、只把反射率量化成 uint8
    只量化 = np.rint(np.clip(X验, 0, 1) * 255) / 255.0
    基准 = 指标(X验, 只量化, 列)

    隐层 = (64, 32) if D > 12 else (24, 12)
    结果 = []

    for k in ks:
        print()
        print('-' * 72)
        print('k = %d   （%d 维 → %d 维，维度压缩 %.2f 倍）' % (k, D, k, D / k))
        print('-' * 72)
        t = time.time()
        ae = 自编码器(D, k, 隐层=隐层, 位数=int(cfg['量化位数']),
                    种子=int(cfg['随机种子']))
        ae.训练(X训, X验, 轮数=轮, 批=int(cfg['批大小']),
                学习率=float(cfg['学习率']), 种子=int(cfg['随机种子']),
                打印=lambda s: print(s))

        量化后 = 指标(X验, ae.重建(X验, 量化开=True), 列)
        不量化 = 指标(X验, ae.重建(X验, 量化开=False), 列)
        pca = PCA基线(k, 位数=int(cfg['量化位数'])).拟合(X训)
        pca指标 = 指标(X验, pca.重建(X验, 量化开=True), 列)

        地板 = float(cfg['噪声地板'])
        print()
        说('验证 RMSE（量化后）', '%.6f   PSNR %.2f dB'
           % (量化后['rmse'], 量化后['psnr']))
        说('验证 RMSE（不量化）', '%.6f   ← 量化只贵这么点'
           % 不量化['rmse'])
        说('对比传感器噪声地板 %.4f' % 地板,
           '低于噪声' if 量化后['rmse'] < 地板
           else '是它的 %.1f 倍' % (量化后['rmse'] / 地板))
        说('线性基线（PCA）同 k', '%.6f   本方法 / 它 = %.3f'
           % (pca指标['rmse'], 量化后['rmse'] / pca指标['rmse']))
        说('训练用时', '%.0f 秒' % (time.time() - t))

        w = os.path.join(p['权重'], '%s_k%d.json' % (scene.NAME, k))
        ae.存(w, 附加=dict(场景=scene.NAME, 列=列, roi=meta['roi'],
                          年份=meta['年份'], 尺度=meta['尺度'], 指标=量化后))
        说('权重写出', os.path.basename(w))

        结果.append(dict(k=k, 降维比=D / k, 量化后=量化后, 不量化=不量化,
                        pca=pca指标, 用时=time.time() - t))

    # --- 汇总 -----------------------------------------------------------
    if len(结果) > 1:
        print()
        print('=' * 72)
        print('率失真一览（验证集 = 空间分块留出）')
        print('=' * 72)
        print('   k   维度压缩   验证 RMSE    PSNR      过噪声地板')
        print('  ' + '-' * 54)
        for r in 结果:
            print('  %2d   %6.2fx   %.6f   %6.2f dB   %s'
                  % (r['k'], r['降维比'], r['量化后']['rmse'],
                     r['量化后']['psnr'],
                     '是' if r['量化后']['rmse'] < float(cfg['噪声地板']) else '否'))
        print()
        print('  压得越狠下载越少，误差越大。挑一个你能接受的，')
        print('  写进 配置.txt 的 k，或下一步加 --k。')

    rp = os.path.join(p['报告'], '%s_训练.json' % scene.NAME)
    json.dump(dict(场景=scene.NAME, 列=列, D=D,
                   训练样本=int(训.sum()), 验证样本=int(验.sum()),
                   空间分块=dict(总块数=n块, 验证块=n验块),
                   基准_只量化=基准, 噪声地板=float(cfg['噪声地板']),
                   结果=结果),
              open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    说('训练结果写出', rp)
    print('\n下一步：python run.py 导权重')
    return 0


if __name__ == '__main__':
    sys.exit(main())
