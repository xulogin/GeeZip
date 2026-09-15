// ===========================================================================
// 场景 · Landsat 四季合成，6 波段 x 4 季度 = 24 维 —— JS 半边
//
// ★★★ 本文件与 landsat季度.py 必须【逐行对应】★★★
// 改了一边一定要改另一边，然后重跑门禁。特征指纹是唯一抓得住漂移的检查。
// ===========================================================================

var FS = {};

FS.NAME     = 'landsat季度';
FS.RAW      = ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'];
FS.BASE     = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'];
FS.SCALE_F  = 0.0000275;
FS.OFFSET   = -0.2;
FS.QUARTERS = [['01-01', '04-01'], ['04-01', '07-01'],
               ['07-01', '10-01'], ['10-01', '12-31']];

FS.FEATURES = (function () {
  var out = [];
  for (var q = 0; q < 4; q++) {
    for (var b = 0; b < 6; b++) {
      out.push('q' + (q + 1) + '_' + FS.BASE[b]);
    }
  }
  return out;
})();

FS.collection = function (roi, year) {
  return ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
    .merge(ee.ImageCollection('LANDSAT/LC08/C02/T1_L2'))
    .filterBounds(roi)
    .filterDate(year + '-01-01', year + '-12-31');
};

// bit 1 = 扩张云   bit 3 = 云   bit 4 = 云影
FS.maskAndScale = function (img) {
  var sr = img.select(FS.RAW).multiply(FS.SCALE_F).add(FS.OFFSET);
  var qa = img.select('QA_PIXEL');
  var clear = qa.bitwiseAnd(1 << 3).eq(0)
    .and(qa.bitwiseAnd(1 << 4).eq(0))
    .and(qa.bitwiseAnd(1 << 1).eq(0));
  var valid = sr.reduce(ee.Reducer.min()).gte(0)
    .and(sr.reduce(ee.Reducer.max()).lte(1));
  var out = sr.updateMask(clear).updateMask(valid).rename(FS.BASE);
  // ★ 不 copyProperties 的话 filterDate 筛不到任何东西，四个季度全空
  return ee.Image(out.copyProperties(img, ['system:time_start']));
};

FS.build = function (roi, year) {
  var col = FS.collection(roi, year).map(FS.maskAndScale);
  var annual = col.median().rename(FS.BASE);

  var parts = [];
  for (var qi = 0; qi < FS.QUARTERS.length; qi++) {
    var q = FS.QUARTERS[qi];
    var im = col.filterDate(year + '-' + q[0], year + '-' + q[1]).median();
    // 该季度没有干净观测的像元，用年度中位数兜底
    im = ee.Image(im).rename(FS.BASE).unmask(annual, false);
    var names = [];
    for (var bi = 0; bi < FS.BASE.length; bi++) {
      names.push('q' + (qi + 1) + '_' + FS.BASE[bi]);
    }
    parts.push(im.select(FS.BASE).rename(names));
  }

  // 全年无观测的像元填 0，保证无空洞
  return ee.Image.cat(parts).select(FS.FEATURES).unmask(0).toFloat();
};
