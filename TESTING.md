# TESTING

无 Docker 环境下的实际验证记录（本机 Python 3.11，依赖安装到用户 site-packages：numpy 2.2.1 / scipy 1.15.1 / fastapi 0.115.6 / sqlalchemy 2.0.36 / redis 5.2.1 / httpx）。

## 运行方式
```bash
cd backend
PYTHONPATH=. python -m tests.test_spillover_math_exhaustive   # 纯标准库，穷举对拍
PYTHONPATH=. python -m tests.test_spillover_flow              # SQLite 内存库 + 假 Redis
PYTHONPATH=. python -m tests.test_spillover_http              # FastAPI TestClient 端到端
```

## 覆盖与结论（最近一次运行全部通过）
1. `test_spillover_math_exhaustive`
   - 概率公式 `π0=(N-m)/N·C(N-1-d,m)/C(N-1,m)`、`π1=留白概率-π0` 对全部 N=3..8、m=0..N-1、d=0..N-1 共 199 个度数用例 + 200 个随机图，与逐方案穷举频率误差 <1e-12。
   - Horvitz–Thompson 总量在全部 C(N,m) 种分派上的期望等于潜在结果真值（外溢 +0.25），验证逆概率加权无偏。
   - 边界：孤立点 π1=0、全员相连 π0=0、m=0 时 π1 全为 0，剔除规则正确。
2. `test_spillover_flow`
   - 三份资料并发补交、名单未到先拒联系/点击、重复补交整份替换；只封存齐全同一批。
   - 缺报点击不算零：缺报时封存 422，补交（真实 0/1）后放行。
   - 已封存批次的联系更正独立留痕（自带 64 位 SHA256）并标记 rejected_sealed；重跑 checksum 与逐人剔除结论不变。
   - 开放批次更正可并入，孤立点补联系后由剔除转为合格。
   - 全员相连场景 π0 全为 0、两臂缺一，拒绝出结果；非法 slot/重复 id/自联系/越界点击/白名单外更正均 422。
3. `test_spillover_http`
   - 未认证 401、viewer 写操作 403；登录、建批、并发补交、齐全度、封存运行、更正、重跑、CSV 导出、审计留痕全链路通过。
   - 导出 CSV 含封存 SHA256 与适用范围文案。
4. 静态检查：`python -m compileall` 后端全通过；`node --check` 前端全部 ES module 通过；原两比例预算算法回归值不变（首情景每组 n=3841 的参考用例保持一致）。

## 未在本机覆盖
- 真实 PostgreSQL16 / Redis7 容器链路与 worker 常驻进程（环境无 Docker）；已用 SQLite+假 Redis 覆盖等价服务逻辑，worker 队列恢复逻辑保留原语义并对缺表容错。建议在有 Docker 的环境执行 `docker compose up -d --build` 后按 README 剧本手工回归一次。
