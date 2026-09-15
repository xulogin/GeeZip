/**
 * GeeZip · 把 GeeLo 装上
 * ============================================================================
 * GeeLo 提供本管线的实跑测试台（`门禁` 和 `出图` 都要用它）。
 * 装插件是更好的路（见 README），这个脚本是**兜底**：
 * 用 Codex、Gemini CLI、Cursor，或者插件装不上时，跑这一条就行。
 *
 *   node 装GeeLo.js              装到 %LOCALAPPDATA%\GeeZip\GeeLo
 *   node 装GeeLo.js --更新       已经装了就 git pull + npm install
 *   node 装GeeLo.js --到 D:\x    装到别处
 *
 * 装完不用改 配置.txt —— `geelo = auto` 会自己找到这个位置。
 *
 * ★ 为什么不做成 npm 依赖：GeeLo 不是一个 npm 包，它是一个带 .bat、
 *   带右键注册表脚本、带 GBK 配置文件的 Windows 工具目录。
 *   git clone 是唯一如实反映它形状的装法。
 */
'use strict';

const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const 仓库 = 'https://github.com/xulogin/GeeLo.git';
const 标志文件 = path.join('测试台', '跑GEE.js');

const 参数 = process.argv.slice(2);
const 要更新 = 参数.includes('--更新') || 参数.includes('--update');
const 到 = (() => {
  const i = 参数.findIndex(a => a === '--到' || a === '--to');
  if (i >= 0 && 参数[i + 1]) { return path.resolve(参数[i + 1]); }
  const 本地 = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  return path.join(本地, 'GeeZip', 'GeeLo');
})();

function say(s) { process.stdout.write(s + '\n'); }
function 横线() { say('─'.repeat(62)); }

/**
 * 跑一条命令，输出直通终端。失败返回 false，不抛。
 *
 * ★ 不用 shell:true。Windows 上 npm 是 npm.cmd，不带扩展名 spawn 找不到，
 *   很容易顺手写成 shell:true —— 但那样 Node 会告警（DEP0190），
 *   而且参数是拼字符串不转义的，路径里有空格就会裂开。
 *   直接把扩展名补上，两个问题一起没有。
 */
function 跑(cmd, args, cwd) {
  const 实际 = (process.platform === 'win32' && cmd === 'npm') ? 'npm.cmd' : cmd;
  say('$ ' + cmd + ' ' + args.join(' '));
  const r = spawnSync(实际, args, { cwd, stdio: 'inherit' });
  return r.status === 0;
}

function 有吗(d) { return fs.existsSync(path.join(d, 标志文件)); }

// ---------------------------------------------------------------------------
say('');
say('══════════════════════════════════════════════════════════════');
say('  GeeZip · 安装 GeeLo');
say('══════════════════════════════════════════════════════════════');
say('');
say('  目标目录：' + 到);
say('');

// ---- git 在不在
try {
  execFileSync('git', ['--version'], { stdio: 'pipe' });
} catch (e) {
  say('★ 没有 git，装不了。');
  say('  去 https://git-scm.com/download/win 装一个，然后重跑本脚本。');
  say('  或者让能上网的人把 GeeLo 目录整个拷给你，放到：');
  say('      ' + 到);
  process.exit(2);
}

// ---- clone 或 pull
横线();
if (有吗(到)) {
  if (!要更新) {
    say('GeeLo 已经在这儿了，跳过下载。（要拉最新版加 --更新）');
  } else if (!跑('git', ['pull', '--ff-only'], 到)) {
    say('');
    say('★ git pull 失败。多半是网络 —— 见下面「连不上 GitHub」。');
    say('  已有的这份还能用，继续装依赖。');
  }
} else {
  if (fs.existsSync(到) && fs.readdirSync(到).length) {
    say('★ 目标目录已存在且非空，但里面不像是 GeeLo（找不到 ' + 标志文件 + '）：');
    say('    ' + 到);
    say('  先把它挪走或删掉，再重跑本脚本。');
    process.exit(2);
  }
  fs.mkdirSync(path.dirname(到), { recursive: true });
  if (!跑('git', ['clone', '--depth', '1', 仓库, 到])) {
    say('');
    say('★ clone 失败。');
    say('');
    say('  ── 连不上 GitHub 怎么办 ────────────────────────────────');
    say('  先明确一点：GeeLo 本来就要连 earthengine.googleapis.com。');
    say('  连不上 GitHub 的机器也一定连不上 Earth Engine ——');
    say('  代理不是为下载额外加的负担，它是这套东西的前提。');
    say('');
    say('  开着代理软件，然后给 git 也配上（端口在代理软件设置里看）：');
    say('      git config --global http.proxy  http://127.0.0.1:7890');
    say('      git config --global https.proxy http://127.0.0.1:7890');
    say('');
    say('  ★ 绝对不要用 git config http.sslVerify false 绕证书错误 ——');
    say('    DNS 被污染时那等于把凭据明文交给中间人。');
    say('');
    say('  实在连不上：让能上网的人把 GeeLo 目录拷给你（U 盘/网盘都行），');
    say('  放到 ' + 到 + ' 即可，效果完全一样。');
    process.exit(1);
  }
}

// ---- npm install（约 104 MB，不进版本库，所以 clone 完必须装）
横线();
const 测试台 = path.join(到, '测试台');
if (fs.existsSync(path.join(测试台, 'node_modules')) && !要更新) {
  say('测试台依赖已装，跳过 npm install。');
} else {
  say('装测试台依赖（@google/earthengine，约 104 MB，要等一会）…');
  if (!跑('npm', ['install', '--no-audit', '--no-fund'], 测试台)) {
    say('');
    say('★ npm install 失败。');
    say('  国内网络建议换源后重试：');
    say('      npm config set registry https://registry.npmmirror.com');
    say('      cd /d "' + 测试台 + '" && npm install');
    process.exit(1);
  }
}

// ---- 收尾
横线();
const 成了 = 有吗(到) && fs.existsSync(path.join(测试台, 'node_modules'));
say('');
if (!成了) {
  say('★ 装完了但自查没过 —— 缺 ' + 标志文件 + ' 或 node_modules。');
  say('  把上面的完整输出丢给你的 AI 助手，它能看出缺什么。');
  process.exit(1);
}
say('══════════════════════════════════════════════════════════════');
say('  GeeLo 装好了：' + 到);
say('══════════════════════════════════════════════════════════════');
say('');
say('  不用改 配置.txt —— geelo = auto 会自己找到这里。');
say('');
say('  下一步：');
say('      python run.py 自检');
say('');
say('  自检要是说「还不知道用哪个 Earth Engine 项目」，跑这一条，');
say('  浏览器会弹出来，点一下「允许」就配好（不用装 Python，不用复制令牌）：');
say('      node "' + path.join(测试台, '认证.js') + '"');
say('');
