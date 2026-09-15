// ===========================================================================
// 编码器 · 由 GeeZip 自动生成，请勿手改
//
//   场景 __SCENE__      __D__ 维 → __K__ 维      量化 uint8
//   权重 __WEIGHTS__
//   重新生成： python run.py 导权重
//
// 这个脚本做一件事：在 GEE 上把 __D__ 维特征栈逐像元压成 __K__ 维 uint8。
// 解码在本地，不在这里 —— 那是分工，不是遗漏。
// ===========================================================================

__SCENE_JS__

// ---------------------------------------------------------------------------
// 编码器权重（Python 端训练导出）
// ---------------------------------------------------------------------------
var MODEL = {
  D: __D__,
  k: __K__,
  L: __L__,                      // uint8 量化上限 = 2^8 - 1
  features: __FEATURES__,
  xMu: __XMU__,
  xSd: __XSD__,
  W: [__W__],
  b: [__B__]
};

var ENC = {};

ENC.toArrays = function (M) {
  return {
    D: M.D, k: M.k, L: M.L, features: M.features,
    xMu: ee.Image(ee.Array(M.xMu)),      // (D,1)
    xSd: ee.Image(ee.Array(M.xSd)),
    W: M.W.map(function (w) { return ee.Image(ee.Array(w)); }),
    b: M.b.map(function (v) { return ee.Image(ee.Array(v)); })
  };
};

// ---------------------------------------------------------------------------
// tanh —— 与 numpy 端、Python-ee 端【同一个公式】
//     tanh(u) = (e^{2u} - 1) / (e^{2u} + 1)
//
// ★ 为什么不直接用 Image.tanh()：
//   数组影像上一元算子的支持不一致，用 exp 组合出来的形式标量和数组都能用，
//   三份实现才能完全对齐。
// ---------------------------------------------------------------------------
ENC.tanh = function (u) {
  var e2 = u.multiply(2).exp();
  return e2.subtract(1).divide(e2.add(1));
};

// ---------------------------------------------------------------------------
// 写法一：数组影像 + matrixMultiply
//
// 逐点预测用这个很好（GeeDL 走的就是这条路）。
// 但【整幅栅格物化】时会撞内存墙，见下面写法二。
//
//   Xn = (X - xMu) / xSd
//   h  = relu(W_i h + b_i)   重复 L-1 次
//   z  = tanh(W_L h + b_L)   收进 [-1,1]
// ---------------------------------------------------------------------------
ENC.encode = function (img, m) {
  var x = img.select(m.features).toArray().toArray(1);      // (D,1)
  var h = x.subtract(m.xMu).divide(m.xSd);

  var L = m.W.length;
  for (var i = 0; i < L - 1; i++) {
    h = m.W[i].matrixMultiply(h).add(m.b[i]).max(0);        // Linear + ReLU
  }
  var z = ENC.tanh(m.W[L - 1].matrixMultiply(h).add(m.b[L - 1]));

  var names = [];
  for (var j = 0; j < m.k; j++) { names.push('z' + j); }
  return z.arrayProject([0]).arrayFlatten([names]).toFloat();
};

// ---------------------------------------------------------------------------
// ★★ 写法二：波段算术，不碰数组影像 —— 出图和导出用这个 ★★
//
// 实测（非推测）：
//     数组影像版  全幅 743x743 @30m  ->  "User memory limit exceeded"
//     本    版    同样范围同样尺度    ->  OK，1.19 MB，5 秒
// 原因是 toArray 给每个像元造了一个数组对象，全幅物化时内存开销巨大。
//
// MLP 的每个隐单元就是个加权和  u_j = sum_i W[j][i]*x_i + b_j，
// 用普通波段算术表达即可，内存开销和普通波段运算一样。
//
// ★ 两版结果【逐位相同】（全幅最大逐像元差 = 0）。
//   门禁验数组版，下载用本版，Python 端每次下载前都会重新对拍。
// ---------------------------------------------------------------------------
ENC.encodeBandMath = function (img, MD) {
  var h = MD.features.map(function (c, i) {
    return img.select([c]).subtract(MD.xMu[i][0]).divide(MD.xSd[i][0]);
  });

  var L = MD.W.length;
  for (var li = 0; li < L; li++) {
    var W = MD.W[li], b = MD.b[li];
    var nh = [];
    for (var j = 0; j < W.length; j++) {
      var acc = ee.Image.constant(b[j][0]);
      for (var i = 0; i < W[j].length; i++) {
        acc = acc.add(h[i].multiply(W[j][i]));
      }
      if (li < L - 1) {
        acc = acc.max(0);                               // ReLU
      } else {
        var e2 = acc.multiply(2).exp();                 // tanh，同一个公式
        acc = e2.subtract(1).divide(e2.add(1));
      }
      nh.push(acc);
    }
    h = nh;
  }
  return ee.Image.cat(h.map(function (im, j) {
    return im.rename('z' + j);
  })).toFloat();
};

// 量化到 uint8：q = round((z+1)/2 * L)
// ★ 必须与 引擎/自编码器.py 的 量化() 完全一致，否则下载下来解不开。
ENC.quantize = function (z, m) {
  return z.add(1).multiply(0.5).multiply(m.L).round().clamp(0, m.L).toUint8();
};

// --- 一致性门禁用：逐条常数影像（慢路径）-------------------------------------
ENC.encodeRows = function (rows, m) {
  var bands = rows.map(function (row, i) {
    var im = ee.Image.constant(row).rename(m.features).toFloat();
    var z = ENC.encode(im, m);
    var names = [];
    for (var j = 0; j < m.k; j++) { names.push('r' + i + '_z' + j); }
    return z.rename(names);
  });
  return ee.Image.cat(bands);
};

// --- 一致性门禁用：一次矩阵乘算完全部 N 条（快路径）---------------------------
// 矩阵乘天然支持批处理： W (out,in) @ X (in,N) -> (out,N)
// 顺带说明「MLP 搬上 GEE 根本不慢」的原因：GEE 的像元并行本身就是这个批处理，
// 每个像元就是 X 的一列。
ENC.encodeMany = function (rows, m) {
  var N = rows.length;
  var Xt = ee.Image(ee.Array(rows).matrixTranspose());        // (D,N)

  var h = Xt.subtract(m.xMu.arrayRepeat(1, N))
            .divide(m.xSd.arrayRepeat(1, N));

  var L = m.W.length;
  for (var i = 0; i < L - 1; i++) {
    h = m.W[i].matrixMultiply(h)
              .add(m.b[i].arrayRepeat(1, N)).max(0);
  }
  var z = ENC.tanh(m.W[L - 1].matrixMultiply(h)
                             .add(m.b[L - 1].arrayRepeat(1, N)));   // (k,N)

  var zn = [], rn = [];
  for (var j = 0; j < m.k; j++) { zn.push('z' + j); }
  for (var r = 0; r < N; r++) { rn.push('r' + r); }
  return z.arrayFlatten([zn, rn]).toFloat();                  // k*N 个波段
};

// __库到此为止__
// ===========================================================================
// 上面是【库】：场景特征栈 + 权重 + 编码器。门禁脚本会原样复用这一段
// （GeeLo 测试台是 vm 沙箱，没有 require，只能内联）。
// 下面是【主程序】：可以直接贴进 GEE Code Editor 跑。
// ===========================================================================

var M = ENC.toArrays(MODEL);
var ROI = ee.Geometry.Rectangle(__ROI__);
var YEAR = __YEAR__;

var STACK = FS.build(ROI, YEAR);

// ★ 出图和导出走波段算术版，数组版全幅物化会 "User memory limit exceeded"
var Z = ENC.encodeBandMath(STACK, MODEL);  // 隐层，float [-1,1]
var Q = ENC.quantize(Z, M);                // 隐层，uint8 —— 下载的就是它

print('输入特征栈波段', STACK.bandNames());
print('隐层波段', Q.bandNames());
print('隐层 uint8 统计（应落在 0~__L__）',
      Q.reduceRegion({reducer: ee.Reducer.minMax(), geometry: ROI,
                      scale: __SCALE__, maxPixels: 1e9, tileScale: 8}));

// 两版对拍：证明换写法没换结果
print('数组版 vs 波段算术版 最大差（抽查 120m）',
      ENC.encode(STACK, M).subtract(Z).abs().reduce(ee.Reducer.max())
        .reduceRegion({reducer: ee.Reducer.max(), geometry: ROI,
                       scale: 120, maxPixels: 1e9, tileScale: 8}));

Map.centerObject(ROI, 11);
Map.addLayer(STACK.select(__RGB__), {min: 0, max: 0.3}, '原始 RGB');
Map.addLayer(Q, {min: 0, max: __L__}, '隐层 uint8');

// 要导出整幅就用这个（Drive 那条路没有同步下载的大小和内存限制）
// Export.image.toDrive({
//   image: Q, description: 'GeeZip_隐层___SCENE___k__K__', region: ROI,
//   scale: __SCALE__, crs: 'EPSG:4326', maxPixels: 1e13
// });
