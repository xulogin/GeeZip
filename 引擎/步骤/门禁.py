# -*- coding: utf-8 -*-
"""门禁 —— 两道核对，都过了才许下载。

    python run.py 门禁

  第一道 · 一致性   同样的权重、同样的输入，本地 numpy 和 GEE 的 JS
                   必须算出同样的隐层。验不了：输入本身对不对。
  第二道 · 特征指纹  两边的特征栈（挑影像、去云、合成）算出同样的值。
                   验不了：模型权重对不对。

★ 缺一不可。GeeDL 的实测：只把 JS 侧云量阈值从 40 改成 60 ——
    一致性门禁  全绿 → 全绿        抓不住
    输出均值    21.897 → 21.788    看不出
    特征指纹    全 0 → 全非 0       ★ 抓住

脚本走 GeeLo 的测试台【实跑】，不是静态审读。
"""
import os
import re
import sys
import json
import argparse
import subprocess

这里 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 这里)
sys.path.insert(0, os.path.join(这里, '步骤'))
import numpy as np                                    # noqa: E402
import 配置 as CFG                                    # noqa: E402
import GeeLo定位                                      # noqa: E402
from 导权重 import 取库, js数组                        # noqa: E402


def 说(k, v):
    print('  %-32s %s' % (k, v)); sys.stdout.flush()


模板 = u'''%(库)s

// ###########################################################################
// 门禁脚本 —— GeeZip 自动生成，请勿手改
// ###########################################################################

var M = ENC.toArrays(MODEL);
var TOL_C = %(tolc)s;      // 一致性阈值
var TOL_F = %(tolf)s;      // 指纹阈值

print('==== 第一道 · 一致性 ====');
print('测试向量条数 =', %(N)d, '   阈值 =', TOL_C);

var ROWS = %(rows)s;
var PYZ  = %(pyz)s;        // (k,N) 拍平：z 优先

// --- 路径一：批量矩阵乘（快）---
var zMany = ENC.encodeMany(ROWS, M);
var names = [];
for (var j = 0; j < MODEL.k; j++) {
  for (var r = 0; r < %(N)d; r++) { names.push('z' + j + '_r' + r); }
}
var diff1 = zMany.rename(names)
  .subtract(ee.Image.constant(PYZ).rename(names)).abs();

// ★ 统计量在服务端算完再 print，否则 print 会被截断
function 汇总(d) {
  var a = d.toArray();
  return ee.Image.cat([
    a.arrayReduce(ee.Reducer.max(),  [0]).arrayGet([0]).rename('max'),
    a.arrayReduce(ee.Reducer.mean(), [0]).arrayGet([0]).rename('mean'),
    d.gt(TOL_C).toArray().arrayReduce(ee.Reducer.sum(), [0])
     .arrayGet([0]).rename('n_over')
  ]).reduceRegion({reducer: ee.Reducer.first(),
                   geometry: ee.Geometry.Point([%(px)s, %(py)s]),
                   scale: 1000, maxPixels: 1e9, bestEffort: true});
}

var s1 = 汇总(diff1);
print('[1] 批量矩阵乘 vs 本地', s1);

// --- 路径二：逐条常数影像（慢，抽 %(N2)d 条对拍）---
// 只对一条路的话，批处理的 arrayRepeat / arrayFlatten 写错了
// 也可能"自洽地错"。两条都得对。
var ROWS2 = ROWS.slice(0, %(N2)d);
var zRows = ENC.encodeRows(ROWS2, M);
var n2 = [];
for (var i2 = 0; i2 < %(N2)d; i2++) {
  for (var j2 = 0; j2 < MODEL.k; j2++) { n2.push('r' + i2 + '_z' + j2); }
}
var diff2 = zRows.rename(n2)
  .subtract(ee.Image.constant(%(pyz2)s).rename(n2)).abs();
var s2 = 汇总(diff2);
print('[2] 逐条常数影像 vs 本地', s2);

// ###########################################################################
print('==== 第二道 · 特征指纹 ====');

var FP_PTS = %(fp点)s;
var FP_VAL = %(fp值)s;
var STACK_FP = FS.build(ee.Geometry.Rectangle(%(roi)s), %(year)d);

var fpDiffs = FP_PTS.map(function (p, i) {
  var got = STACK_FP.select(MODEL.features).reduceRegion({
    reducer: ee.Reducer.first(),
    geometry: ee.Geometry.Point(p), scale: %(scale)d});
  var want = ee.Dictionary.fromLists(MODEL.features, FP_VAL[i]);
  var d = MODEL.features.map(function (f) {
    return ee.Number(got.get(f)).subtract(ee.Number(want.get(f))).abs();
  });
  return ee.Number(ee.List(d).reduce(ee.Reducer.max()));
});
// ★ fpDiffs 是客户端数组，直接 print 会打出 ee 对象签名而不是数值
var fpList = ee.List(fpDiffs);
var fpMax = ee.Number(fpList.reduce(ee.Reducer.max()));
print('逐点最大差', fpList);
print('总体最大差', fpMax);

// ###########################################################################
var m1 = ee.Number(s1.get('max'));
var m2 = ee.Number(s2.get('max'));
var ok = m1.lt(TOL_C).and(m2.lt(TOL_C)).and(fpMax.lt(TOL_F));

print(ee.String('GATE_RESULT ')
  .cat(ee.Algorithms.If(ok, 'PASS', 'FAIL'))
  .cat(' consist_many=').cat(m1.format('%%.3e'))
  .cat(' consist_rows=').cat(m2.format('%%.3e'))
  .cat(' fingerprint=').cat(fpMax.format('%%.3e')));
'''


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 门禁')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--n', type=int, default=200)
    ap.add_argument('--n2', type=int, default=20)
    ap.add_argument('--timeout', type=int, default=900)
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    k = a.k or int(cfg['k'])
    p = CFG.paths()

    脚本 = os.path.join(p['脚本'], '编码器_%s_k%d.js' % (scene.NAME, k))
    tv = os.path.join(p['权重'], '%s_k%d_测试向量.json' % (scene.NAME, k))
    mp = os.path.join(p['数据'], '%s_样本_meta.json' % scene.NAME)
    for f in (脚本, tv, mp):
        if not os.path.exists(f):
            sys.exit('找不到 %s\n  先跑：python run.py 导权重 --k %d' % (f, k))

    print('=' * 72)
    print('门禁   场景 %s   k = %d' % (scene.NAME, k))
    print('=' * 72)

    T = json.load(open(tv, encoding='utf-8'))
    meta = json.load(open(mp, encoding='utf-8'))
    行 = np.array(T['行'])[:a.n]
    z = np.array(T['z'])[:a.n]
    N = len(行)
    fp = meta['指纹']
    说('一致性测试向量', '%d 条 × %d 维' % (N, 行.shape[1]))
    说('慢路径对拍', '%d 条' % a.n2)
    说('特征指纹参考点', '%d 个' % len(fp['点']))
    if len(fp['点']) < 3:
        sys.exit('★ 指纹参考点不足 3 个，第二道门禁无效。重跑 取数。')

    js = 模板 % dict(
        库=取库(脚本),
        tolc=repr(float(cfg['一致性阈值'])), tolf=repr(float(cfg['指纹阈值'])),
        N=N, N2=a.n2,
        rows=js数组(行),
        pyz=js数组(z.T.ravel()),
        pyz2=js数组(z[:a.n2].ravel()),
        fp点=json.dumps(fp['点']), fp值=js数组(np.array(fp['值'])),
        roi=json.dumps(meta['roi']), year=meta['年份'], scale=meta['尺度'],
        px=repr(fp['点'][0][0]), py=repr(fp['点'][0][1]),
    )
    gp = os.path.join(p['脚本'], '门禁_%s_k%d.js' % (scene.NAME, k))
    open(gp, 'w', encoding='utf-8').write(js)
    说('门禁脚本', gp)

    # --- 实跑 ------------------------------------------------------------
    显式 = cfg.get('geelo')
    显式 = None if str(显式).strip() in ('auto', '', '自动') else 显式
    geelo = GeeLo定位.找(显式, cfg['_root'])
    if not geelo:
        sys.exit(GeeLo定位.没找到怎么办(cfg['_root']))
    if not GeeLo定位.装好了吗(geelo):
        sys.exit(GeeLo定位.依赖没装怎么办(geelo))

    print()
    print('  实跑中（GeeLo 测试台，不是静态审读）……')
    env = dict(os.environ)
    pid, _ = CFG.项目ID(cfg)
    if pid:
        env['EE_PROJECT'] = pid
    r = subprocess.run(['node', GeeLo定位.跑GEE(geelo),
                        '--timeout', str(a.timeout), gp],
                       capture_output=True, env=env)
    out = ((r.stdout or b'').decode('utf-8', 'replace') +
           (r.stderr or b'').decode('utf-8', 'replace'))
    print()
    print('-' * 72)
    print(out.strip()[-3500:])
    print('-' * 72)

    rp = os.path.join(p['报告'], '%s_k%d_门禁.txt' % (scene.NAME, k))
    open(rp, 'w', encoding='utf-8').write(out)
    说('门禁输出存档', rp)

    m = re.search(r'GATE_RESULT\s+(PASS|FAIL)([^\n\r]*)', out)
    if not m:
        print('\n★ 门禁没有输出 GATE_RESULT —— 判为不通过。')
        print('  多半是脚本在到达判定行之前就报错了，看上面的实跑输出。')
        return 2

    print()
    print('=' * 72)
    print('  GATE_RESULT %s' % m.group(1))
    print('  %s' % m.group(2).strip())
    print('=' * 72)
    if m.group(1) != 'PASS':
        print('\n★ 门禁没过，禁止下载。先修，别跳过。')
        print('  一致性不过 → 编码器搬错了（权重、激活函数、标准化对不上）')
        print('  指纹不过   → 场景的 .py 和 .js 两边特征栈漂了')
        return 1

    print('\n两道都过了。下一步：python run.py 下载')
    return 0


if __name__ == '__main__':
    sys.exit(main())
