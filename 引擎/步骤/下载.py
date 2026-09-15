# -*- coding: utf-8 -*-
"""下载 —— 云端编码，只把隐层拉回本地。

    python run.py 下载
    python run.py 下载 --roi 101.4 25.4 101.6 25.6 --标签 外推

下三份，都要，用来做诚实的体积对比：
  ① 原始 float32    很多人默认这么下 —— 但这里面有一份是白浪费的
  ② 原始 uint16     ★ 公平基线（反射率 x 10000）
  ③ 隐层 uint8      ★ 实际要下载的那份

★ 压缩比按【实际传输字节】算，基线是 ②。
  float32 比 uint16 大约 1.9 倍，那部分是"不该用 float32"白送的，
  算进压缩比是自欺欺人。

★ 撞上限会自动加密切分：
  getDownloadURL 有 48 MB 同步请求上限，服务端还有内存上限。
  大范围时序数据必然撞，所以切块重试是常规操作，不是异常。
"""
import os
import io
import re
import sys
import json
import time
import zipfile
import argparse
import urllib.request
import urllib.error

这里 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 这里)
import numpy as np                                    # noqa: E402
import 配置 as CFG                                    # noqa: E402
import 编码器_ee as EENC                              # noqa: E402
from 自编码器 import 自编码器                          # noqa: E402


def 说(k, v):
    print('  %-32s %s' % (k, v)); sys.stdout.flush()


def 取一块(img, 区, 参数, 代理, 重试=4):
    """下一块。成功返回 (bytes, None)；撞墙返回 ('超限'|'内存', 说明)。

    ★ 网络级抖动要重试：走代理时 RemoteDisconnected / 超时是常态，
      必须和"服务端说不行"分开 —— 前者重试，后者换策略。
    """
    p = dict(参数); p['region'] = 区
    最后 = None
    for 次 in range(重试):
        try:
            url = img.getDownloadURL(p)
        except Exception as e:
            m = re.search(r'Total request size \((\d+) bytes\)', str(e))
            if m:
                return '超限', int(m.group(1))
            if 'memory' in str(e) or 'capacity' in str(e):
                return '内存', str(e)[:70]
            最后 = e; time.sleep(2 * (次 + 1)); continue

        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({'https': 代理, 'http': 代理})
            if 代理 else urllib.request.ProxyHandler({}))
        try:
            return op.open(url, timeout=1800).read(), None
        except urllib.error.HTTPError as e:
            身 = e.read().decode('utf-8', 'replace')
            if 'memory' in 身 or 'capacity' in 身:
                return '内存', '%d %s' % (e.code, 身[:60].replace('\n', ' '))
            if e.code in (429, 500, 502, 503, 504):
                最后 = e; time.sleep(3 * (次 + 1)); continue
            sys.exit('★ 下载失败 HTTP %d\n  服务端原话：%s'
                     % (e.code, 身[:280].replace('\n', ' ')))
        except Exception as e:
            最后 = e; time.sleep(3 * (次 + 1)); continue
    return '内存', '网络重试 %d 次仍失败：%s' % (重试, type(最后).__name__)


def 下载(ee, img, roi_v, 参数, 目标, 代理, 最大分块=4):
    """切块下载 + 本地拼接。返回 (传输字节, 文件字节, 用时, 块数)。"""
    import rasterio
    from rasterio.merge import merge

    w, s, e, n = roi_v
    t0 = time.time()

    for 边 in range(1, 最大分块 + 1):
        块, 传输, 失败 = [], 0, None
        for iy in range(边):
            for ix in range(边):
                区 = ee.Geometry.Rectangle([
                    w + (e - w) * ix / 边, s + (n - s) * iy / 边,
                    w + (e - w) * (ix + 1) / 边, s + (n - s) * (iy + 1) / 边])
                r, _ = 取一块(img, 区, 参数, 代理)
                if r in ('超限', '内存'):
                    失败 = r; break
                传输 += len(r)
                zf = zipfile.ZipFile(io.BytesIO(r))
                块.append(zf.read(zf.namelist()[0]))
            if 失败:
                break

        if 失败:
            if 边 == 最大分块:
                return '失败', '%s：切到 %dx%d 仍不行' % (失败, 边, 边), 0, 边
            print('        %dx%d 块撞上限（%s），加密切分重试……' % (边, 边, 失败))
            continue

        目录 = os.path.dirname(目标)
        临时 = []
        for i, b in enumerate(块):
            tp = os.path.join(目录, '_块%d.tif' % i)
            open(tp, 'wb').write(b); 临时.append(tp)
        if len(临时) == 1:
            os.replace(临时[0], 目标)
        else:
            srcs = [rasterio.open(x) for x in 临时]
            arr, trans = merge(srcs)
            剖 = srcs[0].profile
            剖.update(height=arr.shape[1], width=arr.shape[2],
                      transform=trans, compress='deflate')
            with rasterio.open(目标, 'w', **剖) as ds:
                ds.write(arr)
            for x in srcs:
                x.close()
            for x in 临时:
                os.remove(x)
        return 传输, os.path.getsize(目标), time.time() - t0, 边 * 边

    return '失败', '未能下载', 0, 0


def main(argv=None):
    cfg = CFG.load()
    ap = argparse.ArgumentParser(prog='run.py 下载')
    ap.add_argument('--scene', default=None)
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--roi', type=float, nargs=4, default=None)
    ap.add_argument('--标签', default='')
    a = CFG.解析(ap, argv)

    scene = CFG.load_scene(cfg, a.scene)
    k = a.k or int(cfg['k'])
    p = CFG.paths()

    wp = os.path.join(p['权重'], '%s_k%d.json' % (scene.NAME, k))
    if not os.path.exists(wp):
        sys.exit('找不到 %s\n  先跑：python run.py 训练' % wp)

    # ★ 门禁必须先过
    gp = os.path.join(p['报告'], '%s_k%d_门禁.txt' % (scene.NAME, k))
    if (not os.path.exists(gp)
            or 'GATE_RESULT PASS' not in open(gp, encoding='utf-8').read()):
        sys.exit('★ 门禁未通过或未运行，禁止下载。\n'
                 '  先跑：python run.py 门禁 --k %d' % k)

    ae, d = 自编码器.读(wp)
    列 = d['列']
    roi_v = a.roi or d['roi']
    # ★ 后缀只由显式 --标签 决定。
    #   别拿"传了 --roi"去推断这是外推：`run.py 全部 --roi ...` 里 --roi
    #   只是"用这块地"，一路透传给每一步。曾经在这里自动加"外推"后缀，
    #   结果 下载 写的是 *_外推_下载.json、解码 找的是 *_下载.json，
    #   整条链断在解码那一步。外推由 `run.py 外推` 显式传 --标签 外推。
    后缀 = a.标签

    ee = CFG.init_ee(cfg)
    roi = ee.Geometry.Rectangle(roi_v)

    print('=' * 72)
    print('下载   场景 %s   k = %d%s'
          % (scene.NAME, k, ('   [%s]' % 后缀) if 后缀 else ''))
    print('=' * 72)
    说('研究区', roi_v)
    说('输入 → 隐层', '%d 维 → %d 维' % (ae.D, ae.k))

    m = EENC.建模型(ee, dict(d, 列=列))

    # --- 下载前自检：Python-ee 那份编码器对不对 -------------------------
    tv = os.path.join(p['权重'], '%s_k%d_测试向量.json' % (scene.NAME, k))
    T = json.load(open(tv, encoding='utf-8'))
    print()
    print('  自检 1：Python-ee 编码器 vs 本地 numpy……')
    最大, 过 = EENC.自检(ee, np.array(T['行'])[:40], np.array(T['z'])[:40], m,
                       阈值=float(cfg['一致性阈值']),
                       点=(sum(roi_v[::2]) / 2, sum(roi_v[1::2]) / 2))
    说('最大绝对差', '%.3e   %s' % (最大, 'OK' if 过 else '★ 不一致'))
    if not 过:
        sys.exit('★ Python-ee 编码器与本地对不上，拒绝下载。')

    栈 = scene.build_stack(ee, roi, d['年份']).select(列).clip(roi)

    # ★ 下载走【波段算术版】。数组版全幅物化会 "User memory limit exceeded"。
    #   但门禁验的是数组版 —— 必须先证明两版等价。
    print('  自检 2：数组影像版 vs 波段算术版……')
    差 = EENC.对拍两版(ee, 栈, ae, 列, m, roi, 尺度=120)
    说('最大逐像元差', '%.3e   %s'
       % (差, 'OK（等价）' if 差 < float(cfg['一致性阈值']) else '★ 两版不等价'))
    if 差 >= float(cfg['一致性阈值']):
        sys.exit('★ 两版编码器不等价，拒绝下载。')

    z = EENC.编码_波段算术(ee, 栈, ae, 列)
    q = EENC.量化(z, m)

    共同 = dict(scale=d['尺度'], crs='EPSG:4326',
                format='ZIPPED_GEO_TIFF', filePerBand=False)
    代理 = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    最大分块 = int(cfg['最大分块'])
    标 = lambda n: os.path.join(
        p['影像'], '%s_k%d%s_%s.tif'
        % (scene.NAME, k, ('_' + 后缀) if 后缀 else '', n))

    print()
    print('-' * 72)
    print('  下载三份（撞上限会自动加密切分）')
    print('-' * 72)

    结果 = {}

    def 跑(名, img, 文件名, 波段, 类型, 额外=None):
        f = 标(文件名)
        传, 文, 秒, 块 = 下载(ee, img, roi_v, 共同, f, 代理, 最大分块)
        if 传 == '失败':
            说(名, '★ 下不动：%s' % 文)
            结果[文件名] = dict(失败=True, 原因=文, 波段=波段, 类型=类型)
            return None
        说(名, '%.2f MB   %.0f 秒   %d 块' % (传 / 1e6, 秒, 块))
        dd = dict(路径=f, 传输字节=传, 文件字节=文, 用时=秒, 分块=块,
                  波段=波段, 类型=类型)
        dd.update(额外 or {})
        结果[文件名] = dd
        return 传

    t1 = 跑('① 原始 float32 (%d 波段)' % ae.D,
           栈.toFloat(), '原始float32', ae.D, 'float32')
    t2 = 跑('② 原始 uint16 (%d 波段) ★基线' % ae.D,
           栈.multiply(10000).round().clamp(0, 65535).toUint16(),
           '原始uint16', ae.D, 'uint16', dict(缩放=10000))
    t3 = 跑('③ 隐层 uint8 (%d 波段) ★成果' % ae.k,
           q, '隐层uint8', ae.k, 'uint8', dict(L=ae.L))

    if not t2 or not t3:
        sys.exit('★ 基线或隐层没下来，无法比较。换小一点的 --roi 试试。')

    print()
    print('-' * 72)
    print('  压缩比（按实际传输字节算）')
    print('-' * 72)
    说('★ 相对 uint16 基线', '%.2f 倍' % (t2 / t3))
    if t1:
        说('  相对 float32', '%.2f 倍（含白送的 %.2f 倍）'
           % (t1 / t3, t1 / t2))
    else:
        说('  相对 float32', '★ float32 根本下不动')
    说('维度压缩比', '%.2f 倍  (%d → %d)' % (ae.D / ae.k, ae.D, ae.k))

    rp = os.path.join(p['报告'], '%s_k%d%s_下载.json'
                      % (scene.NAME, k, ('_' + 后缀) if 后缀 else ''))
    json.dump(dict(场景=scene.NAME, k=k, roi=roi_v, 后缀=后缀, 列=列,
                   D=ae.D, 隐层维=ae.k, 尺度=d['尺度'], 下载=结果,
                   压缩比_对uint16=t2 / t3,
                   压缩比_对float32=(t1 / t3) if t1 else None,
                   自检_pyee=最大, 自检_两版=差),
              open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    说('下载记录', rp)
    print('\n下一步：python run.py 解码%s'
          % ((' --标签 ' + 后缀) if 后缀 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
