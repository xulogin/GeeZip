# -*- coding: utf-8 -*-
"""取数 —— 在研究区里随机采样，落 CSV，并记下【特征指纹】。

    python run.py 取数
    python run.py 取数 --roi 102.6 24.9 102.8 25.1 --year 2023 --npix 60000

★ 这一步只下载几万个像元的数值，不是整幅影像 —— 训练用不着整幅。
★ 指纹是第二道门禁的基准。没有它，门禁只剩一半。
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                    # noqa: E402
import 配置 as CFG                                    # noqa: E402


def 说(k, v):
    print('  %-30s %s' % (k, v)); sys.stdout.flush()


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 取数')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--roi', type=float, nargs=4, default=None,
                    metavar=('W', 'S', 'E', 'N'))
    ap.add_argument('--year', type=int, default=None)
    ap.add_argument('--npix', type=int, default=None)
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    roi_v = a.roi or scene.DEFAULT_ROI
    年 = a.year or scene.DEFAULT_YEAR
    n = a.npix or int(cfg['样本数'])
    列 = list(scene.FEATURES)
    p = CFG.paths()

    print('=' * 72)
    print('取数   场景 %s   %d 维输入' % (scene.NAME, len(列)))
    print('=' * 72)
    说('说明', getattr(scene, '说明', ''))
    说('研究区', roi_v)
    说('年份', 年)
    说('目标样本数', n)

    ee = CFG.init_ee(cfg)
    roi = ee.Geometry.Rectangle(roi_v)
    栈 = scene.build_stack(ee, roi, 年).select(列)

    samp = 栈.sample(region=roi, scale=scene.SCALE, numPixels=n,
                     seed=int(cfg['随机种子']), dropNulls=True,
                     geometries=True, tileScale=8)
    # 经纬度显式写成属性：训练时做空间分块划分要用
    samp = samp.map(lambda f: f.set({
        'lon': f.geometry().coordinates().get(0),
        'lat': f.geometry().coordinates().get(1)}))

    # ★ FeatureCollection.getInfo() 有 5000 元素硬上限
    #   （"Collection query aborted after accumulating over 5000 elements"）。
    #   computeFeatures 会分页，能拿到几万条。
    t = time.time()
    df = ee.data.computeFeatures({'expression': samp,
                                  'fileFormat': 'PANDAS_DATAFRAME'})
    说('computeFeatures', '%s   %.0f 秒' % (str(df.shape), time.time() - t))

    X = df[列].to_numpy(dtype=np.float64)
    好 = np.isfinite(X).all(axis=1)
    df, X = df[好].reset_index(drop=True), X[好]
    说('可用样本', X.shape)
    if len(X) < 2000:
        print('  ★ 样本太少，训出来的东西不可信。换大点的 ROI 或加 --npix。')

    # --- 数值体检：跑通不等于对 -----------------------------------------
    print()
    print('  数值体检（场景自带的领域常识检查）：')
    通过 = True
    for 说明, ok in scene.sanity(np, X, 列):
        标 = '  ' if ok is None else ('OK' if ok else '★ ')
        print('    %s %s' % (标, 说明))
        if ok is False:
            通过 = False
    if not 通过:
        print()
        print('  ★ 有常识检查没过。先搞清楚为什么，别急着往下跑 ——')
        print('    这类问题继续跑下去会一路静默到出图。')

    出 = os.path.join(p['数据'], '%s_样本.csv' % scene.NAME)
    df.to_csv(出, index=False, encoding='utf-8')
    print()
    说('样本写出', 出)

    # --- 特征指纹：第二道门禁的基准 --------------------------------------
    点, 值 = [], []
    for i in range(min(24, len(df))):
        if len(点) >= 6:
            break
        px, py = round(float(df['lon'][i]), 6), round(float(df['lat'][i]), 6)
        d = 栈.reduceRegion(reducer=ee.Reducer.first(),
                           geometry=ee.Geometry.Point([px, py]),
                           scale=scene.SCALE).getInfo()
        if any(d.get(c) is None for c in 列):
            continue
        点.append([px, py]); 值.append([float(d[c]) for c in 列])
    说('特征指纹', '%d 个参考点已记录' % len(点))
    if len(点) < 3:
        print('  ★ 参考点太少，第二道门禁会失效。检查取样。')

    meta = dict(场景=scene.NAME, 列=列, roi=roi_v, 年份=年,
                尺度=scene.SCALE, n=int(len(X)),
                指纹=dict(点=点, 值=值, 尺度=scene.SCALE))
    mp = 出.replace('.csv', '_meta.json')
    json.dump(meta, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    说('meta 写出', mp)
    print('\n下一步：python run.py 训练')
    return 0


if __name__ == '__main__':
    sys.exit(main())
