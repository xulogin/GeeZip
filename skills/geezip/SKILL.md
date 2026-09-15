---
name: geezip
description: Use when remote sensing data is too big to download from Google Earth Engine — 大范围/长时序影像下载慢、撞配额或 EECU 上限、只能分块导、Drive 任务排队，或者用户下回来第一件事就是降维。GeeZip 把降维挪到云上：编码器在 GEE 上逐像元把几十个波段压成几个 uint8 波段，只下载这一份，回本地解码还原。也用于「云端先降维再下载」「压缩遥感影像」「隐层/嵌入下载」这类需求。仅支持 Windows。
---

# GeeZip · 在云上压好再下载

**存在理由：下遥感数据最花时间的一步，是把几十个波段原样搬回本地——
而很多人下回来第一件事就是降维。占带宽的那一步白走了。**

```
云端（GEE）              带宽            本地
特征栈 D 维  →  编码器  →  k 维 uint8  →  解码器  →  还原 D 维
                前向传播                  反向传播在这边训
```

实测：6 波段少下 4.2 倍，24 维时序少下 8.1 倍，还原误差小于 Landsat 自身的
辐射定标精度（0.005 反射率）。

## 工具在哪

**`<GeeZip>` = 本文件所在目录的上两级**（本文件是 `<GeeZip>/skills/geezip/SKILL.md`）。

- **Claude Code**：可以直接用 `${CLAUDE_PLUGIN_ROOT}`
- **Codex / 其他**：`${CLAUDE_PLUGIN_ROOT}` **不会展开**，先算成绝对路径再执行
- **直接 clone 的**：`<GeeZip>` 就是仓库根目录

**不要问用户路径**，你自己能算出来。

---

## ★ 先判断：这个活该不该用 GeeZip

| 用户要什么 | 用什么 |
|---|---|
| 写个 NDVI/RSEI/LST 脚本、调某个 GEE 报错 | **geelo**，不是这个 |
| 分类/回归出图 | **geedl**（要 σ 或神经网络）或 GEE 自带 RF |
| **数据太大下不动 / 下载太慢 / 撞配额** | ★ **GeeZip** |
| **要下几十个波段、几十个时相** | ★ **GeeZip**，波段越多越划算 |
| 只下一景、几个波段、小范围 | 直接下就行，**别上 GeeZip** |
| 要逐位精确的存档 | **别用**，它是有损的 |

**判据一句话：下载量是瓶颈才用它。** 小数据直接下更快。

---

## 第一步：自检

```bash
cd /d "<工作目录>" && python "<GeeZip>/run.py" 自检
```

| 结果 | 你怎么做 |
|---|---|
| 全部 OK | **直接开工，别汇报"我检查了环境"** |
| 缺 Python 模块 | `pip install -r "<GeeZip>/requirements.txt"` |
| **没找到 GeeLo** | 跑 `node "<GeeZip>/装GeeLo.js"`，它自己 clone + npm install |
| GeeLo 依赖没装 | 按自检打印的那条 `npm install` 跑 |
| **EE 项目 ID 没配** | 跑 `node "<GeeLo>/测试台/认证.js"`，自动开浏览器 |

★ 认证完提醒用户：`EE_PROJECT` 是 `setx` 写的，**当前终端读不到**。
后续要么新开终端，要么临时带 `$env:EE_PROJECT='<id>';`（PowerShell）。

★ **绝对不要让用户把 `credentials` 内容贴给你**，也不要自己读它、打印它。

★ 网络失败时先让用户确认代理软件在跑 —— `earthengine.googleapis.com`
不通的话自检会报一串失败，根因往往只是代理没开。

---

## 只有一个入口

```bash
python run.py 自检       换电脑第一件事
python run.py 取数       云端随机取样（只下几万个像元，不是整幅）
python run.py 训练       本地训编码器+解码器（量化感知）
python run.py 导权重     编码器搬上 GEE，生成 JS 脚本
python run.py 门禁       ★ 两道核对，不过就挡住后面
python run.py 下载       云端编码，只把隐层拉回来
python run.py 解码       本地还原 + 与原图对比出图
python run.py 汇总       收拢成一份报告
python run.py 全部       上面一整串
python run.py 外推 --roi W S E N    换块没训练过的地验泛化
python run.py 新建 "D:\某目录"      在别处开一条新管线
```

参数原样透传：`python run.py 取数 --scene landsat季度`、
`python run.py 训练 --k扫 2 3 4 6`。

**没有编号脚本。全部走 `run.py`。**

---

## ★ 五条铁律

### 1. 两道门禁都过了才许下载

| 门禁 | 验什么 | **验不了什么** |
|---|---|---|
| 一致性 | 同样输入 → 本地和 GEE 同样输出 | **输入本身对不对** |
| 特征指纹 | 两边特征栈算出同样的值 | 模型权重对不对 |

**缺一不可。** 特征栈在 `场景/<name>.py` 和 `场景/<name>.js` 里各写了一遍。

结论不是你眼睛看的，是脚本自己判的：末尾打印 `GATE_RESULT PASS/FAIL`，
`下载` 先读这行，FAIL 就直接拒绝跑。**不要想办法绕过。**

### 2. 「跑通」不等于「对」

GEE 惰性计算，零报错也可能全错。**本项目实际踩到过的静默故障：**

| 故障 | 后果 |
|---|---|
| `multiply()` 丢了 `system:time_start` | `filterDate` 筛不到任何东西，**四个季度全空**，下游才报 "no bands" |
| 反向传播分母漏乘 D | 梯度大了 D 倍，**照样收敛**，只是收敛到别处；只有数值梯度检查抓得住 |
| 数组影像全幅物化 | `User memory limit exceeded`，但小范围测试完全正常 |

交付前一定要再问：**这些数字讲得通吗？量级对吗？**

### 3. 先小后大，省配额

Debug 阶段先拿一小块 ROI、少量样本（`--npix 8000 --轮数 60`），
通了再放大。**取数只下几万个像元**，比下整幅便宜得多——这是本工具
省配额的关键，别退回去下整幅来训练。

### 4. 改场景改两个文件，改完从 `取数` 重跑

`场景/<name>.py` 和 `场景/<name>.js`，两边特征栈逐行对应。`引擎/` 别动。

### 5. 诚实报告

- 压缩比按**实际传输字节**算，基线用 **uint16**，不是 float32
  （float32 比 uint16 大约 1.9 倍，那部分是"不该用 float32"白送的）
- 还原误差要和**传感器自身的定标精度**比（Landsat ≈ 0.005 反射率）
- 换块地会不会崩，跑 `run.py 外推` 用数据说话，**退化了就照实说**

---

## ★ 一条关键的工程经验

**别用 `toArray` + `matrixMultiply` 去物化整幅栅格。**

逐点预测用它没问题（GeeDL 就是这么干的），但整幅下载时会撞内存墙：

| | 全幅 743×743 @30m |
|---|---|
| 数组影像版 | `User memory limit exceeded` |
| **波段算术版** | **OK，1.19 MB，5 秒** |

MLP 的每个隐单元就是个加权和 `u_j = Σ W[j][i]·x_i + b_j`，
用普通波段算术表达即可。两版结果**逐位相同**（实测全幅最大差 = 0）。

引擎里两版都有：门禁验数组版，下载用波段算术版，每次下载前自动对拍。

---

## 下载会撞的两堵墙（都会自动处理，但要知道）

```
Total request size (66245880 bytes) must be less than or equal to 50331648 bytes
Earth Engine memory capacity exceeded
```

`getDownloadURL` 有 **48 MB 同步请求上限**，服务端另有内存上限。
大范围时序数据必然撞。`下载` 步骤会**自动把边长翻倍重试**，最多 4×4。

走代理时 `RemoteDisconnected` 是常态，网络级错误会自动重试。

---

## 换研究对象

复制 `场景/_新场景模板.py` 和 `.js`，改 `配置.txt` 的 `scene`：

1. **`build_stack()`** —— 特征栈（**两边都改**）
2. **`FEATURES`** —— 波段名和顺序，两边必须一致
3. **`sanity()`** 和 **`CAVEAT`** —— 领域常识检查 + 已知偏差。**千万别省**

自带两个场景：`landsat年度`（6 维，先用它跑通）、`landsat季度`（24 维，收益大得多）。

---

## 别污染用户的文件夹

- 探针、临时脚本 → **临时目录**
- `产物/` 是全部输出，删掉不影响代码
- `<GeeZip>` 里的东西**别改**，那是插件本体。要在别处干活就 `run.py 新建`

报告要给证据：说"少下了 N 倍"就附实跑输出。跑不通就说跑不通。

---

## 要更多细节时读这些

| 什么时候 | 读哪份 |
|---|---|
| 完整规矩、目录地图 | `<GeeZip>/AGENTS.md` |
| 写普通 GEE 脚本 | **geelo** skill |
| 在 GEE 上跑神经网络、要逐像元 σ | **geedl** skill |

---

## 环境事实

- Windows + Python 3.8+（numpy / pandas / scikit-learn / rasterio /
  scikit-image / matplotlib / earthengine-api，**不需要 torch / tensorflow**）
  + Node.js 20.19+
- 前置依赖 **GeeLo**，提供实跑测试台。`配置.txt` 的 `geelo = auto` 会自己找
- PowerShell 5.1 里 `&&` 不可用，用 `;` 或 `if ($?) { ... }`
- 中文 Windows 控制台是 GBK，**加新 print 时别用花哨符号**
- 凭据在 `%USERPROFILE%\.config\earthengine\credentials`，**不在仓库里**
