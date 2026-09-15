// ===========================================================================
// 场景 · Landsat 年度合成，6 个波段 —— JS 半边
//
// ★★★ 本文件与 landsat年度.py 必须【逐行对应】★★★
// 改了一边一定要改另一边，然后重跑门禁。
//
// 一致性门禁只验「同样的输入 -> 同样的输出」，验不了「输入本身对不对」。
// 两边特征代码一旦漂了，脚本照样跑通、图照样出、数是错的 ——
// 只有【特征指纹】抓得住。
//
// 这段会被 导权重 步骤原样拼进生成的编码器脚本里
// （GeeLo 测试台是 vm 沙箱，没有 require，只能内联）。
// ===========================================================================

var FS = {};

FS.NAME     = 'landsat年度';
FS.RAW      = ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'];
FS.FEATURES = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'];
FS.SCALE_F  = 0.0000275;      // 对应 .py 的 缩放
FS.OFFSET   = -0.2;           // 对应 .py 的 偏移

// --- 对应 .py 的 集合() -----------------------------------------------------
FS.collection = function (roi, year) {
  return ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
    .merge(ee.ImageCollection('LANDSAT/LC08/C02/T1_L2'))
    .filterBounds(roi)
    .filterDate(year + '-01-01', year + '-12-31');
};

// --- 对应 .py 的 去云并缩放() ------------------------------------------------
// bit 1 = 扩张云   bit 3 = 云   bit 4 = 云影   ★位号写死，不许改
FS.maskAndScale = function (img) {
  var sr = img.select(FS.RAW).multiply(FS.SCALE_F).add(FS.OFFSET);
  var qa = img.select('QA_PIXEL');
  var clear = qa.bitwiseAnd(1 << 3).eq(0)
    .and(qa.bitwiseAnd(1 << 4).eq(0))
    .and(qa.bitwiseAnd(1 << 1).eq(0));
  var valid = sr.reduce(ee.Reducer.min()).gte(0)
    .and(sr.reduce(ee.Reducer.max()).lte(1));
  var out = sr.updateMask(clear).updateMask(valid).rename(FS.FEATURES);

  // ★★ copyProperties 不是可有可无 ★★
  //   multiply/add 会丢掉原影像属性，system:time_start 一并没了，
  //   之后 filterDate 在 map 过的集合上一个都筛不到。
  //   GEE 只在下游报 "Image with no bands"，报错位置离真 bug 很远。
  return ee.Image(out.copyProperties(img, ['system:time_start']));
};

// --- 对应 .py 的 build_stack() ----------------------------------------------
FS.build = function (roi, year) {
  var col = FS.collection(roi, year).map(FS.maskAndScale);
  return col.median().rename(FS.FEATURES).select(FS.FEATURES).toFloat();
};
