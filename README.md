# 彩票预测模型实验台

双色球、超级大乐透的科普实验：把常见「看走势选号」写成可复现的统计程序，放到真实开奖上逐期考试。结论预期是这些方法推不出下一期。页面不是购彩建议。

## 能做什么

- 从中国福彩网、中国体彩竞彩网拉取公开开奖，写入本地 SQLite。
- 用同一套历史，给 15 个实验模型各生成 5 注，并按期号落库。已保存的号码不会被后来的计算改掉；新增模型时只补缺票。
- 走步回测：只用某一期之前的历史预测该期，前 180 期作预热，一直考到最新一期。
- 开奖后把已保存预测逐注对号，按公开固定奖级估算金额（浮动奖用保守常量）。
- 每天凌晨 03:00（`Asia/Shanghai`）自动拉开奖并刷新下期预测。

## 页面怎么读

地址默认 `http://127.0.0.1:5179/`。从上到下：

1. 先说结论：最好模型的每元回报，对照闭眼乱选。
2. 最新开奖与近 20 期号码。
3. 开奖长什么样：近 60 期和值、近 120 期各号出现次数。
4. 模型偏好热力图：1.0 倍表示与均匀随机相同。
5. 下一期 5 注，以及模型之间选号重合度。
6. 全历史回测：每元回报、累计盈亏、相对随机的波动带、奖级构成、命中个数分布。
7. 实盘留存：已对号的账面与逐注结果。

图表使用随包的 AntV G2 v5（`frontend/vendor/g2.min.js`），不依赖外网 CDN。

## 彩种与金额

| 彩种 | 选号 | 单注 | 开奖日 |
| --- | --- | --- | --- |
| 双色球 | 红球 6/33，蓝球 1/16 | 2 元 | 周二、四、日 |
| 超级大乐透 | 前区 5/35，后区 2/12 | 2 元 | 周一、三、六 |

奖级金额写在 `backend/src/config.py` 的 `prizes`。一等奖、二等奖等浮动奖使用固定保守值，只用于横向比较，不是实际派奖。

## 15 个实验模型

定义在 `backend/src/config.py` 的 `MODELS`，计算在 `backend/src/models.py`。

| id | 名称 | 在检验什么 |
| --- | --- | --- |
| random | 随机基线 | 均匀随机，对照组 |
| frequency | 频率统计 | 近窗热号是否更常出现 |
| gap | 遗漏回补 | 当前遗漏接近历史均值时是否该买 |
| markov | 马尔可夫链 | 上期号码能否估计下期 |
| cooccur | 共现关联 | 历史上同场出现的号是否还会一起出 |
| pattern | 结构约束 | 和值、奇偶、区间是否可延续 |
| recency | 近期动量 | 短窗相对长窗升温的号 |
| ewma | 指数平滑 | 越近的开奖权重越高 |
| position | 位置分布 | 号码在排序位置上的习惯 |
| repeat | 重复间隔 | 上期号隔几期再出现 |
| decay | 遗漏衰减 | 「冷号该弃」 |
| overdue | 超期加权 | 「超过平均间隔就该出」 |
| antimarkov | 反转转移 | 「上期之后很少接着出的号」 |
| neighbor | 邻号跟随 | 上期号码 ±1 |
| ensemble | 模型融合 | 其余统计模型边际概率的平均 |

另有 `uniform_theory`（理论均匀），只作概率参照，不参与买票和回测。

抽样规则：每个模型先得到各区号码权重，再用种子 `random.Random(f"{彩种}:{期号}:{模型}")` 不放回抽取。同一历史、同一模型，号码可复现。温度固定 1.05。

## 目录

```
lottery-lab/
  backend/app.py                 Flask 接口与静态页
  backend/backfill_predictions.py  给近 N 期补缺失模型的票
  backend/precompute.py          预计算回测与概率缓存
  backend/src/config.py          彩种、奖级、模型目录
  backend/src/models.py          权重与抽样
  backend/src/analytics.py       回测、预测、实盘对号
  backend/src/scraper.py         官方开奖抓取与缺期补齐
  backend/src/scheduler.py       每日 03:00
  backend/src/db.py              SQLite
  frontend/                      页面、样式、G2
  data/lottery.db                开奖、预测、报告缓存
  Dockerfile / docker-compose.yml
  deploy_nas.py                  可选：发布到局域网 NAS
```

## 数据

SQLite 路径默认是项目下 `data/lottery.db`，可用环境变量 `LOTTERY_DB` 改掉。启动时开启 WAL。

表：

- `draws`：开奖号码、日期、销量、奖池。
- `predictions`：按 `(game, based_on_issue, model, ticket_index)` 唯一。`source` 为 `live` 或 `backfill`。回填不覆盖实盘。
- `reports`：回测与概率缓存。签名形如 `期数:最新期号:models-v4`，模型集合变化时换版本号以使旧缓存失效。
- `meta`：最近抓取时间等。

安装包里的库是一份快照（约双色球 2081 期、大乐透 2941 期，截止期号以库内最新记录为准）。装好后点「更新官方开奖」，或等到凌晨任务，即可续上新期。

## 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/overview` | 两个彩种的期数与最新一期 |
| GET | `/api/schedule` | 定时任务状态 |
| POST | `/api/schedule/run` | 立刻拉两个彩种并刷新预测 |
| GET | `/api/<game>/history?limit=` | 最近开奖，`game` 为 `ssq` 或 `dlt` |
| GET | `/api/<game>/stats` | 近 120 期频率与遗漏 |
| GET | `/api/<game>/predict` | 下期预测；缺模型则补票 |
| GET | `/api/<game>/backtest` | 全历史回测，首次可能较慢 |
| GET | `/api/<game>/record` | 已保存预测的对号结果 |
| POST | `/api/sync/<game>` | 只更新一个彩种 |

历史不足 30 期时预测返回 409；不足 220 期时回测返回 409。

## 回测口径

- 预热 `WARMUP = 180`。
- 每期每模型 5 注，每注 2 元。
- 只使用该期之前的开奖。
- 「跑赢随机」只表示这一段样本里的数字差异，不代表下一期可预测。彩票每期独立开奖，返奖率约为一半，长期每元回报应低于 1。

## 部署到 NAS（可选）

`deploy_nas.py` 用环境变量连接，不把密码写入文件：

```powershell
$env:NAS_HOST='nas.example'
$env:NAS_USER='your-user'
$env:NAS_PASSWORD='your-password'
$env:NAS_DIR='/home/your-user/lottery-lab'
python deploy_nas.py
```

`NAS_DIR` 必须显式给出。网页端口是 `5179`。远端已有 `data/lottery.db` 时不覆盖；只有远端没有库，或设置 `SEED_DB=1`，才会上传本机库。该脚本额外需要 `pip install paramiko`，日常运行网页不需要它。不要把主机、账号、密码写进仓库。

## 边界

本仓库不提供购彩建议，也不保证奖级常量与当期官方公告一致。抓取依赖官网接口；接口变更时只需改 `backend/src/scraper.py`。
