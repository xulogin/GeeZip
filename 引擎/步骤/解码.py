# -*- coding: utf-8 -*-
"""解码 —— 本地还原 + 与原图对比。

    python run.py 解码
    python run.py 解码 --标签 外推

到这一步云端那半边已经做完了：隐层已经在本地。
剩下的全在本地 —— 解码器从来就该留在这边。

产出：还原影像、对比图、一份数字报告。
"""
import os
import sys
import json
import argparse

这里 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 这里)
import numpy as np                                    # noqa: E402
import rasterio                                       # noqa: E402
import 配置 as CFG                                    # noqa: E402
from 自编码器 import 自编码器                          # noqa: E402

import matplotlib                                     # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt                       # noqa: E402
matplotlib.rcParams['font.sans-serif'] = [
    'Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False


def 说(k, v):
    print('  %-32s %s' % (k, v)); sys.stdout.flush()


def 拉伸(a, lo=2, hi=98):
    """百分位拉伸，只为看图，不参与任何计算。"""
    a = np.asarray(a, dtype=np.float64)
    m = np.isfinite(a)
    if not m.any():
        return np.zeros_like(a)
    p1, p2 = np.percentile(a[m], [lo, hi])
    return np.clip((a - p1) / max(p2 - p1, 1e-12), 0, 1)


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 解码')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--标签', default='')
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    k = a.k or int(cfg['k'])
    尾 = ('_' + a.标签) if a.标签 else ''
    p = CFG.paths()

    dl = os.path.join(p['报告'], '%s_k%d%s_下载.json' % (scene.NAME, k, 尾))
    if not os.path.exists(dl):
        sys.exit('找不到 %s\n  先跑：python run.py 下载' % dl)
    D = json.load(open(dl, encoding='utf-8'))
    ae, _ = 自编码器.读(os.path.join(p['权重'],
                                   '%s_k%d.json' % (scene.NAME, k)))
    列 = D['列']

    print('=' * 72)
    print('解码   场景 %s   k = %d%s' % (scene.NAME, k, 尾))
    print('=' * 72)

    with rasterio.open(D['下载']['原始uint16']['路径']) as ds:
        原始 = ds.read().astype(np.float64) / D['下载']['原始uint16']['缩放']
        剖面 = ds.profile
    with rasterio.open(D['下载']['隐层uint8']['路径']) as ds:
        隐 = ds.read().astype(np.float64)

    说('原始影像', '%s   %d 波段' % (str(原始.shape[1:]), 原始.shape[0]))
    说('隐层影像', '%s   %d 波段 uint8' % (str(隐.shape[1:]), 隐.shape[0]))
    if 原始.shape[1:] != 隐.shape[1:]:
        sys.exit('★ 两幅尺寸不一致，没法逐像元比。')

    C, H, W = 原始.shape
    kk = 隐.shape[0]

    # --- 本地解码 -------------------------------------------------------
    还原 = np.clip(ae.解码(ae.反量化(隐.reshape(kk, -1))).reshape(C, H, W), 0, 1)
    说('解码完成', '%d 维 → %d 波段' % (kk, C))

    有效 = 原始.sum(axis=0) > 1e-9
    说('有效像元', '%d / %d  (%.1f%%)'
       % (有效.sum(), H * W, 有效.sum() / (H * W) * 100))

    o, r = 原始[:, 有效], 还原[:, 有效]
    e = r - o
    rmse = float(np.sqrt((e ** 2).mean()))
    psnr = float(20 * np.log10(1.0 / max(rmse, 1e-12)))
    逐 = np.sqrt((e ** 2).mean(axis=1))
    地板 = float(cfg['噪声地板'])

    print()
    print('-' * 72)
    print('  还原精度（全部在【下载到本地之后】算的）')
    print('-' * 72)
    说('整体 RMSE（反射率）', '%.6f' % rmse)
    说('MAE', '%.6f' % float(np.abs(e).mean()))
    说('PSNR', '%.2f dB' % psnr)
    说('★ 对比传感器噪声 %.4f' % 地板,
       '低于噪声（压缩损失小于卫星自身测量误差）' if rmse < 地板
       else '是它的 %.1f 倍' % (rmse / 地板))

    try:
        from skimage.metrics import structural_similarity as ssim
        ss = []
        for i in range(C):
            o2 = np.where(有效, 原始[i], 0)
            r2 = np.where(有效, 还原[i], 0)
            ss.append(float(ssim(o2, r2,
                                 data_range=float(max(o2.max() - o2.min(), 1e-6)))))
        说('SSIM 均值', '%.5f' % float(np.mean(ss)))
        说('SSIM 最低波段', '%s  %.5f' % (列[int(np.argmin(ss))], min(ss)))
    except ImportError:
        ss = []
        说('SSIM', '（没装 scikit-image，跳过）')

    print()
    print('  逐波段 RMSE：')
    for i, c in enumerate(列):
        print('    %-16s %.6f' % (c, 逐[i]))

    # --- 写还原影像 ------------------------------------------------------
    剖面.update(dtype='uint16', count=C, compress='deflate')
    还原路径 = os.path.join(p['影像'],
                          '%s_k%d%s_还原.tif' % (scene.NAME, k, 尾))
    with rasterio.open(还原路径, 'w', **剖面) as ds:
        ds.write(np.clip(还原 * 10000, 0, 65535).astype(np.uint16))
    print()
    说('还原影像', 还原路径)

    # --- 出图：原图 / 隐层 / 还原 ----------------------------------------
    rgb名 = list(getattr(scene, 'RGB', 列[:3]))
    idx = [列.index(c) for c in rgb名 if c in 列]
    if len(idx) != 3:
        idx = [0, min(1, C - 1), min(2, C - 1)]
    成RGB = lambda X: np.dstack([拉伸(np.where(有效, X[i], np.nan)) for i in idx])

    基MB = D['下载']['原始uint16']['传输字节'] / 1e6
    隐MB = D['下载']['隐层uint8']['传输字节'] / 1e6

    fig, ax = plt.subplots(1, 3, figsize=(17, 6.4))
    ax[0].imshow(成RGB(原始))
    ax[0].set_title('原始影像 RGB\n%d 波段 uint16 · 下载 %.2f MB' % (C, 基MB),
                    fontsize=13)
    隐图 = (np.dstack([拉伸(np.where(有效, 隐[i], np.nan)) for i in range(3)])
           if kk >= 3 else 拉伸(np.where(有效, 隐[0], np.nan)))
    ax[1].imshow(隐图, cmap=None if kk >= 3 else 'viridis')
    ax[1].set_title('压缩后（云端编码的隐层）\n%d 波段 uint8 · 下载 %.2f MB'
                    % (kk, 隐MB), fontsize=13)
    ax[2].imshow(成RGB(还原))
    ax[2].set_title('本地解码还原 RGB\nRMSE %.5f · PSNR %.1f dB%s'
                    % (rmse, psnr,
                       (' · SSIM %.4f' % np.mean(ss)) if ss else ''),
                    fontsize=13)
    for x in ax:
        x.set_xticks([]); x.set_yticks([])
    fig.suptitle('%s · %d 维 → %d 维 · 少下 %.1f 倍\n云端编码 → 只下载隐层 → 本地解码'
                 % (scene.NAME, C, kk, D['压缩比_对uint16']),
                 fontsize=15, y=1.03)
    plt.tight_layout()
    图1 = os.path.join(p['图'], '%s_k%d%s_三联.png' % (scene.NAME, k, 尾))
    plt.savefig(图1, dpi=140, bbox_inches='tight')
    plt.close()
    说('三联图', 图1)

    # --- 误差图 ----------------------------------------------------------
    误差 = np.where(有效, np.sqrt(((还原 - 原始) ** 2).mean(axis=0)), np.nan)
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    ax[0].imshow(成RGB(还原)); ax[0].set_title('还原影像', fontsize=13)
    im = ax[1].imshow(误差, cmap='inferno', vmin=0,
                      vmax=float(np.nanpercentile(误差, 99)))
    ax[1].set_title('逐像元 RMSE\n中位 %.5f · 传感器噪声 %.3f'
                    % (float(np.nanmedian(误差)), 地板), fontsize=13)
    plt.colorbar(im, ax=ax[1], fraction=0.046)
    for x in ax:
        x.set_xticks([]); x.set_yticks([])
    plt.tight_layout()
    图2 = os.path.join(p['图'], '%s_k%d%s_误差.png' % (scene.NAME, k, 尾))
    plt.savefig(图2, dpi=140, bbox_inches='tight')
    plt.close()
    说('误差图', 图2)

    结 = dict(场景=scene.NAME, k=k, 标签=a.标签, 列=列, D=C, 隐层维=kk,
             有效像元=int(有效.sum()), rmse=rmse, psnr=psnr,
             mae=float(np.abs(e).mean()),
             逐波段rmse=dict(zip(列, [round(float(v), 6) for v in 逐])),
             ssim均值=float(np.mean(ss)) if ss else None,
             下载=D['下载'], 压缩比_对uint16=D['压缩比_对uint16'],
             噪声地板=地板, 图=[图1, 图2])
    rp = os.path.join(p['报告'], '%s_k%d%s_结果.json' % (scene.NAME, k, 尾))
    json.dump(结, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    说('结果写出', rp)

    print()
    print('=' * 72)
    print('  %d 维压到 %d 维，下载量 %.2f MB → %.2f MB（少 %.1f 倍），'
          % (C, kk, 基MB, 隐MB, D['压缩比_对uint16']))
    print('  还原误差 %.5f 反射率 —— %s。'
          % (rmse, '低于传感器自身噪声 %.3f' % 地板 if rmse < 地板
             else '是传感器噪声的 %.1f 倍' % (rmse / 地板)))
    print('=' * 72)
    print('\n下一步：python run.py 汇总')
    return 0


if __name__ == '__main__':
    sys.exit(main())
