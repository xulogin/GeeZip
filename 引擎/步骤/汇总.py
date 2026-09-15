# -*- coding: utf-8 -*-
"""汇总 —— 把跑过的所有结果收拢成一份报告。

    python run.py 汇总

★ 只收拢【实跑出来的】文件。缺什么就说缺什么，不编不补。
"""
import os
import re
import sys
import json
import glob

这里 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 这里)
import 配置 as CFG                                    # noqa: E402


def MB(x):
    return '%.2f MB' % (x / 1e6)


def main(argv=None):
    cfg = CFG.load()
    p = CFG.paths()
    行 = []
    W = 行.append

    W('# GeeZip 运行结果')
    W('')
    W('> 全部数字由本管线实跑产出，非推测。')
    W('')

    # --- 端到端 ---------------------------------------------------------
    结果 = []
    for f in sorted(glob.glob(os.path.join(p['报告'], '*_结果.json'))):
        try:
            结果.append(json.load(open(f, encoding='utf-8')))
        except Exception:
            pass

    if 结果:
        W('## 下载量与还原精度')
        W('')
        W('| 场景 | 区域 | 输入 | 隐层 | 基线下载 | 隐层下载 | 压缩比 | RMSE | PSNR | SSIM | 对比传感器噪声 |')
        W('|---|---|---|---|---|---|---|---|---|---|---|')
        for r in 结果:
            比 = r['rmse'] / r['噪声地板']
            W('| %s | %s | %d 维 | %d 维 uint8 | %s | %s | **%.2fx** | '
              '%.5f | %.2f dB | %s | %s |'
              % (r['场景'], r.get('标签') or '本区', r['D'], r['隐层维'],
                 MB(r['下载']['原始uint16']['传输字节']),
                 MB(r['下载']['隐层uint8']['传输字节']),
                 r['压缩比_对uint16'], r['rmse'], r['psnr'],
                 ('%.4f' % r['ssim均值']) if r.get('ssim均值') else '-',
                 '**低于噪声**' if 比 < 1 else '%.1f 倍' % 比))
        W('')
        W('> 压缩比按【实际传输字节】算，基线是 uint16 反射率，不是 float32。')
        W('> float32 比 uint16 大约 1.9 倍，那部分是"不该用 float32"白送的。')
        W('')

        # 泛化对照
        配 = {}
        for r in 结果:
            配.setdefault(r['场景'], {})[r.get('标签') or '本区'] = r
        对照 = [(s, d['本区'], d['外推']) for s, d in 配.items()
                if '本区' in d and '外推' in d]
        if 对照:
            W('## 换个地方还能用吗')
            W('')
            W('| 场景 | 本区 RMSE | 外推区 RMSE | 退化 |')
            W('|---|---|---|---|')
            for s, 本, 外 in 对照:
                W('| %s | %.5f | %.5f | **%.1f 倍** |'
                  % (s, 本['rmse'], 外['rmse'], 外['rmse'] / 本['rmse']))
            W('')
            W('> 越是靠区域专属结构压得狠，编码器越不能搬去别的地方。')
            W('> 单期影像的波段关系比较普适；季相物候是地域性的，跨区会明显退化。')
            W('> 要跨区用，训练时就得把多个区域的样本混进去。')
            W('')

    # --- 率失真 ----------------------------------------------------------
    训 = sorted(glob.glob(os.path.join(p['报告'], '*_训练.json')))
    if 训:
        W('## 压多狠，差多少')
        W('')
        for f in 训:
            t = json.load(open(f, encoding='utf-8'))
            if len(t['结果']) < 2:
                continue
            W('### %s（%d 维输入）' % (t['场景'], t['D']))
            W('')
            W('训练 %d / 验证 %d 样本，%d 个空间块留出 %d 块做验证。'
              % (t['训练样本'], t['验证样本'],
                 t['空间分块']['总块数'], t['空间分块']['验证块']))
            W('')
            W('| k | 维度压缩 | 验证 RMSE | PSNR | 过噪声地板 |')
            W('|---|---|---|---|---|')
            for r in t['结果']:
                W('| %d | %.2fx | %.6f | %.2f dB | %s |'
                  % (r['k'], r['降维比'], r['量化后']['rmse'],
                     r['量化后']['psnr'],
                     '是' if r['量化后']['rmse'] < t['噪声地板'] else '否'))
            W('')

    # --- 门禁 -------------------------------------------------------------
    门 = sorted(glob.glob(os.path.join(p['报告'], '*_门禁.txt')))
    if 门:
        W('## 两道门禁')
        W('')
        W('| 运行 | 一致性（批量） | 一致性（逐条） | 特征指纹 | 判定 |')
        W('|---|---|---|---|---|')
        for f in 门:
            s = open(f, encoding='utf-8').read()
            m = re.search(r'GATE_RESULT\s+(PASS|FAIL)\s+consist_many=(\S+)\s+'
                          r'consist_rows=(\S+)\s+fingerprint=(\S+)', s)
            if m:
                W('| %s | %s | %s | %s | **%s** |'
                  % (os.path.basename(f).replace('_门禁.txt', ''),
                     m.group(2), m.group(3), m.group(4), m.group(1)))
        W('')
        W('阈值：一致性 %.0e，指纹 %.0e。两道都过才允许下载。'
          % (float(cfg['一致性阈值']), float(cfg['指纹阈值'])))
        W('')

    if not 结果 and not 训:
        W('_还没有任何实跑结果。先跑 `python run.py 全部`。_')
        W('')

    out = os.path.join(p['报告'], '结果.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(行))
    print('汇总报告： %s' % out)
    print('端到端结果： %d 组' % len(结果))
    return 0


if __name__ == '__main__':
    sys.exit(main())
