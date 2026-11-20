"""穷举固定名额分派，对拍留白两情形概率与IPW点击差估计。

仅用标准库，可直接 `python -m backend.tests.test_spillover_math_exhaustive`
或在 backend 目录下 `python tests/test_spillover_math_exhaustive.py`。
设计：N 人、固定名额 m 个已投（无放回等概率，C(N,m) 种等可能分派）。
对每个留白人员 i：
  pi1(i) = P(i 留白 且 至少一个联系人为已投)
  pi0(i) = P(i 留白 且 没有任何联系人为已投)
公式（组合数精确计算）：
  pi0 = C(N-1-d, m) / C(N-1, m) * (N-m)/N，其中 d=|联系人|
  pi1 = (N-m)/N - pi0
"""
from itertools import combinations
from math import comb


def probs_formula(N, m, d):
    if not (0 <= d <= N - 1):
        raise ValueError('联系人数须在 0 到 N-1 之间')
    p_holdout = (N - m) / N
    # 留白条件下，m 个名额全部落在其余 N-1-d 个非联系人中的概率
    if m > N - 1 - d:
        p_none_given_holdout = 0.0
    else:
        p_none_given_holdout = comb(N - 1 - d, m) / comb(N - 1, m)
    pi0 = p_holdout * p_none_given_holdout
    pi1 = p_holdout - pi0
    return pi0, pi1


def probs_exhaustive(N, m, i, contacts_of_i):
    """穷举每种分派（已投集合），统计 i 的两种留白情形频率。"""
    cnt0 = cnt1 = total = 0
    for treated in combinations(range(N), m):
        total += 1
        if i in treated:
            continue
        if any(c in treated for c in contacts_of_i):
            cnt1 += 1
        else:
            cnt0 += 1
    return cnt0 / total, cnt1 / total


def ipw_difference(people, probs):
    """按每人落入两情形的概率加权的点击率差。任一概率为零者剔除。"""
    num0 = den0 = num1 = den1 = 0.0
    eligible = 0
    for p in people:
        pi0, pi1 = probs[p['id']]
        if pi0 <= 0.0 or pi1 <= 0.0:
            continue
        eligible += 1
        if p.get('click') is not None:
            if p['state'] == 0:
                num0 += p['click'] / pi0
                den0 += 1.0 / pi0
            else:
                num1 += p['click'] / pi1
                den1 += 1.0 / pi1
    mean0 = num0 / den0 if den0 else None
    mean1 = num1 / den1 if den1 else None
    diff = (mean1 - mean0) if (mean0 is not None and mean1 is not None) else None
    return mean0, mean1, diff, eligible


def test_formula_matches_exhaustive():
    rng_seed = 12345
    import random
    rng = random.Random(rng_seed)
    cases = []
    for N in range(3, 9):
        for m in range(0, N):
            # 每个可能的联系人度数都测到
            for d in range(0, N):
                cases.append((N, m, d))
    for N, m, d in cases:
        i = 0
        contacts = set(range(1, min(N, 1 + d)))
        f0, f1 = probs_formula(N, m, d)
        e0, e1 = probs_exhaustive(N, m, i, contacts)
        assert abs(f0 - e0) < 1e-12, (N, m, d, f0, e0)
        assert abs(f1 - e1) < 1e-12, (N, m, d, f1, e1)
        assert abs((f0 + f1) - ((N - m) / N)) < 1e-12
    # 随机图再抽一批
    for trial in range(200):
        N = rng.randint(3, 10)
        m = rng.randint(0, N - 1)
        i = rng.randrange(N)
        rest = [x for x in range(N) if x != i]
        rng.shuffle(rest)
        contacts = set(rest[: rng.randint(0, N - 1)])
        d = len(contacts)
        f0, f1 = probs_formula(N, m, d)
        e0, e1 = probs_exhaustive(N, m, i, contacts)
        assert abs(f0 - e0) < 1e-12 and abs(f1 - e1) < 1e-12
    print(f'公式对拍通过：{len(cases)} 个确定性度数用例 + 200 个随机图用例')


def test_ipw_unbiased_exhaustive():
    """构造固定潜在点击结果，穷举所有分派，验证IPW/HT估计的无偏性。

    网络：4 人链 0-1-2-3，N=4, m=2。点位 1、2 的 pi0=0（留白必有已投联系人），
    按规则剔除；合格总体只剩点位 0、3（端点，d=1）。
    对每个情形 s∈{0,1}，Horvitz–Thompson 总量 T_s=Σ 1{state=s}·Y/pi_s，
    在全部 C(N,m) 种分派上取平均，应等于合格总体在该情形下的潜在结果总量。
    """
    N, m = 4, 2
    edges = [(0, 1), (1, 2), (2, 3)]
    adj = {i: set() for i in range(N)}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    base_click = {0: 0.10, 1: 0.20, 2: 0.30, 3: 0.40}

    def potential_click(person, exposed):
        # 潜在结果：有已投联系人时外溢 +0.25
        return min(1.0, base_click[person] + (0.25 if exposed else 0.0))

    probs = {i: probs_formula(N, m, len(adj[i])) for i in range(N)}
    eligible = {i for i in range(N) if probs[i][0] > 0 and probs[i][1] > 0}
    assert eligible == {0, 3}
    truth_total0 = sum(potential_click(i, False) for i in eligible)
    truth_total1 = sum(potential_click(i, True) for i in eligible)
    truth_diff = (truth_total1 - truth_total0) / len(eligible)

    ht0_sum = ht1_sum = diff_sum = n_diff = 0
    n_assign = comb(N, m)
    for treated in combinations(range(N), m):
        ht0 = ht1 = 0.0
        arm0_people = arm1_people = 0
        for i in eligible:
            if i in treated:
                continue
            exposed = any(c in treated for c in adj[i])
            y = potential_click(i, exposed)
            pi_s = probs[i][1] if exposed else probs[i][0]
            if exposed:
                ht1 += y / pi_s
                arm1_people += 1
            else:
                ht0 += y / pi_s
                arm0_people += 1
        ht0_sum += ht0
        ht1_sum += ht1
        if arm0_people and arm1_people:
            diff_sum += ht1 / arm1_people - ht0 / arm0_people
            n_diff += 1
    assert abs(ht0_sum / n_assign - truth_total0) < 1e-9
    assert abs(ht1_sum / n_assign - truth_total1) < 1e-9
    # 每臂HT总量期望无偏 ⇒ 差值（同合格总体等权均值口径）期望等于真值 0.25
    assert abs((ht1_sum - ht0_sum) / n_assign / len(eligible) - 0.25) < 1e-9
    print(f'IPW/HT 无偏性穷举通过：{n_assign} 种分派，其中 {n_diff} 种可直接估差值；'
          f'期望点击差 {((ht1_sum - ht0_sum) / n_assign / len(eligible)):.6f} = 真值 0.25')


def test_zero_probability_exclusion():
    # 孤立受众：N=5, m=4。孤立点 d=0：pi1=0（永不曝光），应剔除；pi0=0.2
    pi0, pi1 = probs_formula(5, 4, 0)
    assert pi1 == 0.0 and abs(pi0 - 0.2) < 1e-12
    # 全员相连 d=N-1：pi0=0（留白必有人被投，除非 m=0），应剔除
    pi0b, pi1b = probs_formula(5, 4, 4)
    assert pi0b == 0.0 and abs(pi1b - 0.2) < 1e-12
    # m=0 时全员留白且无人被投：pi1 全为 0
    pi0c, pi1c = probs_formula(5, 0, 2)
    assert pi1c == 0.0 and abs(pi0c - 1.0) < 1e-12
    print('零概率剔除规则通过：孤立点/全连/m=0 边界均正确')


if __name__ == '__main__':
    test_formula_matches_exhaustive()
    test_ipw_unbiased_exhaustive()
    test_zero_probability_exclusion()
    print('全部数学验证通过')
