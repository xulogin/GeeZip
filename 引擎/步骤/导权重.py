# -*- coding: utf-8 -*-
"""导权重 —— 把编码器搬上 GEE。

    python run.py 导权重
    python run.py 导权重 --k 3

把训好的【编码器】权重内嵌成 JS 字面量，拼上场景的特征栈，
生成一个可以直接贴进 GEE Code Editor、也能被 GeeLo 测试台实跑的脚本。

★ 只导编码器。解码器留本地 —— 那是分工，不是遗漏。
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402
import 配置 as CFG                                    # noqa: E402
from 自编码器 import 自编码器                          # noqa: E402

分隔标记 = '__库到此为止__'


def 说(k, v):
    print('  %-32s %s' % (k, v)); sys.stdout.flush()


def js数(x, 位=10):
    """浮点转 JS 字面量。位数不能省 —— 精度掉了一致性门禁就过不了。"""
    return repr(round(float(x), 位))


def js数组(a, 位=10):
    a = np.asarray(a)
    if a.ndim == 1:
        return '[' + ','.join(js数(v, 位) for v in a) + ']'
    return '[' + ',\n   '.join(js数组(r, 位) for r in a) + ']'


def 取库(脚本路径):
    """把生成脚本的【库】部分切出来，供门禁脚本内联复用。"""
    s = open(脚本路径, encoding='utf-8').read()
    i = s.find(分隔标记)
    if i < 0:
        sys.exit('★ %s 里找不到分隔标记，脚本格式不对' % 脚本路径)
    return s[:s.rfind('\n', 0, i)]


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 导权重')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--k', type=int, default=None)
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    k = a.k or int(cfg['k'])
    p = CFG.paths()

    wp = os.path.join(p['权重'], '%s_k%d.json' % (scene.NAME, k))
    if not os.path.exists(wp):
        sys.exit('找不到 %s\n  先跑：python run.py 训练 --k %d' % (wp, k))

    ae, d = 自编码器.读(wp)
    列 = d['列']

    print('=' * 72)
    print('导权重   场景 %s   k = %d' % (scene.NAME, k))
    print('=' * 72)
    说('编码器结构', ' → '.join(map(str, ae.enc尺寸)))
    参数 = sum(w.size for w in ae.eW) + sum(b.size for b in ae.eb)
    说('编码器参数量', '%d 个' % 参数)
    if 参数 > 50000:
        print('  ★ 超过 5 万参数，GEE 上可能很慢或超预算。考虑减小隐层。')

    模板 = open(os.path.join(cfg['_root'], '引擎', '模板', '模板_编码器.js'),
               encoding='utf-8').read()
    场景js = open(scene._js, encoding='utf-8').read()
    rgb = json.dumps(list(getattr(scene, 'RGB', 列[:3])))

    替换 = {
        '__SCENE__': scene.NAME,
        '__SCENE_JS__': 场景js,
        '__WEIGHTS__': os.path.basename(wp),
        '__D__': str(ae.D), '__K__': str(ae.k), '__L__': str(ae.L),
        '__FEATURES__': '[' + ','.join('"%s"' % c for c in 列) + ']',
        '__XMU__': js数组(ae.xMu), '__XSD__': js数组(ae.xSd),
        '__W__': ',\n  '.join(js数组(w) for w in ae.eW),
        '__B__': ',\n  '.join(js数组(b) for b in ae.eb),
        '__ROI__': json.dumps(d['roi']),
        '__YEAR__': str(d['年份']),
        '__SCALE__': str(d['尺度']),
        '__RGB__': rgb,
    }
    js = 模板
    for k2, v2 in 替换.items():
        js = js.replace(k2, v2)

    出 = os.path.join(p['脚本'], '编码器_%s_k%d.js' % (scene.NAME, k))
    open(出, 'w', encoding='utf-8').write(js)
    说('编码器脚本', 出)
    说('脚本大小', '%.1f KB（可以直接贴进 Code Editor）'
       % (len(js.encode('utf-8')) / 1024))

    # --- 门禁要用的测试向量：从真实样本里抽，不是随便造的 ----------------
    csv = os.path.join(p['数据'], '%s_样本.csv' % scene.NAME)
    df = pd.read_csv(csv)
    rng = np.random.default_rng(int(cfg['随机种子']))
    idx = rng.choice(len(df), size=min(200, len(df)), replace=False)
    行 = df[列].to_numpy(dtype=np.float64)[idx]

    z = ae.编码(行.T).T
    q = ae.量化(z)
    tp = os.path.join(p['权重'], '%s_k%d_测试向量.json' % (scene.NAME, k))
    json.dump(dict(场景=scene.NAME, k=k, 列=列, 行=行.tolist(),
                   z=z.tolist(), q=q.tolist()),
              open(tp, 'w', encoding='utf-8'), indent=0)
    说('测试向量', '%d 条' % len(行))
    说('隐层范围', '[%.4f, %.4f]  %s'
       % (z.min(), z.max(),
          '（tanh 收口正常）' if abs(z).max() <= 1.0 else '★ 越界！'))
    说('量化值范围', '[%d, %d]   应在 [0,%d]' % (q.min(), q.max(), ae.L))

    print('\n下一步：python run.py 门禁')
    return 0


if __name__ == '__main__':
    sys.exit(main())
