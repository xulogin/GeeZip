// ===========================================================================
// 场景模板 · JS 半边 —— 复制这份改成你自己的
//
// ★★★ 本文件与同名 .py 必须【逐行对应】★★★
// 改了一边一定要改另一边，然后重跑核对。
//
// 第一道核对（一致性）只验「同样的输入 -> 同样的输出」，
// 验不了「输入本身对不对」。两边特征代码一旦漂了，
// 脚本照样跑通、图照样出、数是错的 —— 只有【特征指纹】抓得住。
//
// 这段会被 导权重 步骤原样拼进生成的编码器脚本里
// （GeeLo 测试台是 vm 沙箱，没有 require，只能内联）。
// ===========================================================================

var FS = {};

FS.NAME     = '_新场景模板';
FS.FEATURES = ['b1', 'b2', 'b3'];      // ← 必须与 .py 的 FEATURES 完全一致

// --- 对应 .py 的 build_stack() ----------------------------------------------
FS.build = function (roi, year) {
  var col = ee.ImageCollection('你的/数据集')
    .filterBounds(roi)
    .filterDate(year + '-01-01', year + '-12-31');

  // ★ 用了 multiply / add 之类的运算记得 copyProperties，否则
  //   system:time_start 会丢，filterDate 在 map 过的集合上筛不到东西：
  //     return ee.Image(out.copyProperties(img, ['system:time_start']));

  // ★ 结果里不能有空洞，有空洞隐层下载下来解不了码。
  //   该兜底就兜底，但兜法要和 .py 完全一致。

  return col.median().select(FS.FEATURES).toFloat();
};
