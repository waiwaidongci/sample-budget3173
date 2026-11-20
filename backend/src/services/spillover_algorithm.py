'''留白人群外溢点击差：固定名额等概率分派下的逆概率加权估计。

设计：N 人中以无放回简单随机抽样固定 m 人投放。留白者 i（联系人度数 d_i）有两种情形：
  情形1 留白且至少一个联系人为已投；情形0 留白且没有任何联系人为已投。
边际概率（仅依赖 N、m、d_i，与具体网络结构无关）：
  pi0(i) = (N-m)/N · C(N-1-d_i, m)/C(N-1, m)
  pi1(i) = (N-m)/N - pi0
任一 pi 为零的人不进比较；点击按 1/pi_s 做 Hajek（归一化逆概率）加权求两组点击率之差。
'''
import math
from collections import deque
from src.config.domain import DOMAIN

SP = DOMAIN['spillover']

def _log_comb(n, k):
    if k < 0 or k > n:
        return None  # 组合数为 0
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)

def situation_probs(N, m, d):
    '''返回 (pi0, pi1)；结构上不可能的组合以精确 0 表示。'''
    if not (0 <= m <= N):
        raise ValueError('投放名额必须在 0 到总人数之间')
    if not (0 <= d <= N - 1):
        raise ValueError('联系人度数必须在 0 到 N-1 之间')
    p_holdout = (N - m) / N
    if m == 0:
        return p_holdout, 0.0
    if m == N:
        return 0.0, 0.0
    log_den = _log_comb(N - 1, m)
    log_num = _log_comb(N - 1 - d, m)
    pi0 = 0.0 if log_num is None else p_holdout * math.exp(log_num - log_den)
    pi0 = min(max(pi0, 0.0), p_holdout)  # 修正浮点误差
    return pi0, p_holdout - pi0

def _components(adj, ids):
    '''返回每人所在连通分量规模，用于“全员相连”自检。'''
    seen = set(); size_of = {}
    for start in ids:
        if start in seen:
            continue
        q = deque([start]); comp = []
        while q:
            x = q.popleft()
            if x in seen:
                continue
            seen.add(x); comp.append(x)
            q.extend(y for y in adj[x] if y not in seen)
        for x in comp:
            size_of[x] = len(comp)
    return size_of

def calculate(snapshot, params=None):
    roster = snapshot['roster']; edges = snapshot['edges']; clicks = snapshot['clicks']
    N = len(roster)
    if N < 2:
        raise ValueError('名单至少需要 2 人才能识别留白外溢')
    m = sum(1 for slot in roster.values() if slot == 'treated')
    if not (0 < m < N):
        raise ValueError('固定名额必须同时存在已投与留白人员（0 < m < N），否则两种留白情形无法同时出现')
    if N > SP['max_persons']:
        raise ValueError(f"批次人数超过小型研究上限 {SP['max_persons']}")

    adj = {pid: set() for pid in roster}
    for a, b in edges:
        adj[a].add(b); adj[b].add(a)
    ids = list(roster)
    treated_set = {pid for pid in ids if roster[pid] == 'treated'}
    degrees = {pid: len(adj[pid]) for pid in ids}
    probs = {pid: situation_probs(N, m, degrees[pid]) for pid in ids}
    comp_size = _components(adj, ids)

    eligible, excluded = [], []
    for pid in ids:
        pi0, pi1 = probs[pid]
        if roster[pid] == 'treated':
            excluded.append((pid, '已投人员不参与留白比较'))
        elif pi0 <= 0.0 or pi1 <= 0.0:
            if degrees[pid] == 0:
                excluded.append((pid, '孤立受众：无联系人，有已投联系人情形概率为零'))
            else:
                excluded.append((pid, '联系人覆盖过多：留白时必然有联系人被投，无已投联系人情形概率为零'))
        else:
            eligible.append(pid)

    missing = [pid for pid in eligible if pid not in clicks]
    if missing:
        raise ValueError('合格留白人员存在缺报点击（缺报不算零），请补交点击资料或联系更正后再封存：'
                         + ','.join(missing[:10]) + ('…' if len(missing) > 10 else ''))

    num0 = den0 = num1 = den1 = 0.0
    arm_counts = {0: 0, 1: 0}; detail = []
    for pid in ids:
        d = degrees[pid]; pi0, pi1 = probs[pid]; slot = roster[pid]
        state = None
        if slot == 'holdout':
            state = 1 if any(c in treated_set for c in adj[pid]) else 0
        click = clicks.get(pid)
        weight = None
        if pid in eligible:
            pi_s = pi1 if state == 1 else pi0
            weight = 1.0 / pi_s
            if state == 1:
                num1 += click * weight; den1 += weight; arm_counts[1] += 1
            else:
                num0 += click * weight; den0 += weight; arm_counts[0] += 1
        detail.append([pid, '已投' if slot == 'treated' else '留白', d,
                       round(pi0, 8), round(pi1, 8),
                       '有已投联系人' if state == 1 else '无已投联系人' if state == 0 else '—',
                       click if click is not None else '缺报',
                       round(weight, 6) if weight else '不适用',
                       '是' if pid in eligible else '否'])
    if arm_counts[0] == 0 or arm_counts[1] == 0:
        raise ValueError('两种留白情形均需至少一名合格且有点击的人员，当前无法估计点击差')

    mean0 = num0 / den0; mean1 = num1 / den1; diff = mean1 - mean0
    self_check = _self_check(degrees, comp_size, probs, N, m, ids)
    metrics = {
        '总人数 N': N, '固定投放名额 m': m, '留白人数': N - m,
        '比较适用人数(两情形概率均为正)': len(eligible),
        '剔除人数(含已投与零概率)': len(excluded),
        '情形1人数 有已投联系人': arm_counts[1], '情形0人数 无已投联系人': arm_counts[0],
        '情形1 Hajek有效样本量': round(den1, 4), '情形0 Hajek有效样本量': round(den0, 4),
        '情形1 加权点击率': round(mean1, 8), '情形0 加权点击率': round(mean0, 8),
        '点击差(有联系人-无联系人)': round(diff, 8),
        '相对差(以情形0为基准)': round(diff / mean0, 8) if mean0 > 0 else None,
    }
    interpretation = (f'合格留白人群中，有已投联系人者加权点击率 {mean1:.4f}，无已投联系人者 {mean0:.4f}，'
                      f'点击差 {diff:+.4f}' + (f'，相对差 {diff / mean0:+.2%}。' if mean0 > 0 else '（情形0点击率为0，相对差不可定义）。'))
    return {
        'metrics': metrics, 'interpretation': interpretation,
        'caveat': SP['caveat'],
        'applicability': SP['applicability'] + f' 本批 {N} 人中 {len(eligible)} 人适用、{len(excluded)} 人剔除。',
        'excluded_detail': [{'人员': pid, '原因': why} for pid, why in excluded],
        'self_check': self_check,
        'columns': ['人员', '分派', '联系人数', 'pi0_无已投联系人', 'pi1_有已投联系人', '留白情形', '点击', '逆概率权重', '纳入比较'],
        'rows': detail, 'table_title': '逐人情形概率、权重与纳入范围',
    }

def _self_check(degrees, comp_size, probs, N, m, ids):
    '''用孤立受众与全员相连两个极端结构验证概率规则；不通过则算法拒绝出结果。'''
    checks = []
    for pid in ids:
        pi0, pi1 = probs[pid]
        if degrees[pid] == 0:
            checks.append({'结构': '孤立受众', '人员': pid, '期望': 'pi1=0 且 pi0=留白概率',
                           '通过': pi1 == 0.0 and abs(pi0 - (N - m) / N) < 1e-12})
        if comp_size[pid] == N and degrees[pid] == N - 1:
            checks.append({'结构': '全员相连', '人员': pid, '期望': 'pi0=0 且 pi1=留白概率',
                           '通过': pi0 == 0.0 and abs(pi1 - (N - m) / N) < 1e-12})
        if not (pi0 >= 0 and pi1 >= 0 and abs(pi0 + pi1 - (N - m) / N) < 1e-12 and pi0 + pi1 <= 1 + 1e-12):
            checks.append({'结构': '概率不变量', '人员': pid, '期望': 'pi0+pi1=留白概率', '通过': False})
    if not all(c['通过'] for c in checks):
        raise ValueError('内置概率自检未通过，拒绝输出：' + str([c for c in checks if not c['通过']]))
    return {'通过': True, '检查项数': len(checks),
            '说明': '孤立受众 pi1 恒为 0；全员相连（且 0<m<N）pi0 恒为 0；所有人员 pi0+pi1 等于其留白概率。',
            '明细': checks[:50]}
