"""画面融合亮度校准。

在多机拼接几何成立（覆盖连续、逐机可行、联合安装点互避）的前提下，为
2~3 台投影机求一组全局一致的亮度衰减，并为每个相邻重叠带生成从左机到
右机的线性单调渐变权重，使非重叠区与重叠带的加权预测亮度全部落入目标
容差。

亮度模型
--------
设第 k 台实测基准亮度 B_k（cd/m²），衰减（输出保留系数）g_k ∈
[gmin_k, gmax_k]，1.0 表示不衰减、越小衰减越多：

* 非重叠区：                L(u) = B_k · g_k
* 重叠带 [a,b] 内（左机 k、右机 k+1），采用从左机到右机的线性渐变
  权重 w(u) = (b-u)/(b-a)（左机权重 1→0、右机权重 0→1，严格单调）：
      L(u) = w(u)·B_L(u)·g_k + (1-w(u))·B_R(u)·g_{k+1}
  其中 B_L(u)/B_R(u) 为两侧沿幕布坐标实测的单侧亮度采样（分段线性
  插值，端点处按最近采样平推）。

求解
----
以各台 g_k 与公共裕量 s 为变量（s 表示全部点位相对容差边界的最小
归一化裕量），所有亮度约束除以目标亮度 T 归一化后构成线性规划：

    非重叠区： 1-δ+s ≤ (B_k/T) g_k ≤ 1+δ-s
    采样点：   1-δ+s ≤ w(B_L/T)g_k + (1-w)(B_R/T)g_{k+1} ≤ 1+δ-s
    边界：     gmin_k ≤ g_k ≤ gmax_k，s ≥ 0，δ = 容差/T

最大化 s（Bland 准则两阶段单纯形，结果确定且不依赖求解器库）。同一台
参与左右两个重叠带时其 g_k 只有一个变量，两侧约束同时成立。

无解时不输出任何校准值：按约束分组做“移除后恢复可行”的归因诊断，定位
到设备（衰减范围无共同解）或具体重叠带的采样点，同时给出按目标就近
夹取的兜底衰减用于前端标记超差采样。
"""

from geometry import EPS

# LP 数值容差（归一化后系数量级约为 1）
LP_EPS = 1e-9


# ==========================================================================
# 两阶段单纯形（最大化；Bland 进基/出基规则，结果确定、不会循环）
# ==========================================================================

def simplex(c, rows, feasibility_only=False):
    """求 max c·x s.t. rows；rows 每项 (a, sense, rhs)，sense ∈ <=、>=、==。

    返回 (status, x)，status ∈ {"optimal", "infeasible", "unbounded"}。
    feasibility_only=True 时仅做第一阶段，x 为 None。
    所有 rhs 内部翻号为非负。
    """
    n = len(c)
    norm_rows = []
    for a, sense, rhs in rows:
        aa = list(a)
        bb = rhs
        if bb < -LP_EPS:
            aa = [-v for v in aa]
            bb = -bb
            sense = {"<=": ">=", ">=": "<=", "==": "=="}[sense]
        norm_rows.append((aa, sense, bb))

    n_slack = sum(1 for _, s, _ in norm_rows if s == "<=")
    n_surp = sum(1 for _, s, _ in norm_rows if s == ">=")
    n_art = sum(1 for _, s, _ in norm_rows if s in (">=", "=="))
    n_cols = n + n_slack + n_surp + n_art
    rhs_j = n_cols

    tab, basis = [], []
    isl = isur = iar = 0
    art_rows = []
    for a, sense, b in norm_rows:
        row = [0.0] * (n_cols + 1)
        for j, v in enumerate(a):
            row[j] = v
        row[rhs_j] = b
        if sense == "<=":
            q = n + isl
            row[q] = 1.0
            isl += 1
        elif sense == ">=":
            q = n + n_slack + isur
            row[q] = -1.0
            isur += 1
            qa = n + n_slack + n_surp + iar
            row[qa] = 1.0
            art_rows.append(len(tab))
            iar += 1
        else:  # "=="
            q = n + n_slack + n_surp + iar
            row[q] = 1.0
            art_rows.append(len(tab))
            iar += 1
        tab.append(row)
        basis.append(q)
    m = len(tab)

    def pivot(obj):
        """对给定目标行执行 Bland 单纯形，True=已最优，False=无界。"""
        while True:
            enter = -1
            for j in range(n_cols):
                if j >= n + n_slack + n_surp:
                    continue                       # 人工列不进基
                if obj[j] < -LP_EPS:
                    enter = j
                    break
            if enter < 0:
                return True
            leave, ratio, tie_q = -1, None, None
            for i in range(m):
                a = tab[i][enter]
                if a <= LP_EPS:
                    continue
                r = tab[i][rhs_j] / a
                q = basis[i]
                if (ratio is None or r < ratio - LP_EPS or
                        (abs(r - ratio) <= LP_EPS and
                         (tie_q is None or q < tie_q))):
                    leave, ratio, tie_q = i, r, q
            if leave < 0:
                return False                       # 无界
            pr = tab[leave]
            piv = pr[enter]
            for j in range(n_cols + 1):
                pr[j] /= piv
            for i in range(m):
                if i == leave:
                    continue
                f = tab[i][enter]
                if abs(f) <= LP_EPS:
                    continue
                for j in range(n_cols + 1):
                    tab[i][j] -= f * pr[j]
            f = obj[enter]
            for j in range(n_cols + 1):
                obj[j] -= f * pr[j]
            basis[leave] = enter

    # ---- 第一阶段：max w = -Σ 人工变量 ----
    # 目标行 w + Σ 人工变量 = 0：人工列初值 +1，再减去各人工基行使之
    # 对基规范（人工列归 0）；表中 obj[rhs] 即当前 w（≤0），w=0 为可行。
    if art_rows:
        obj1 = [0.0] * (n_cols + 1)
        for qi in range(n_art):
            obj1[n + n_slack + n_surp + qi] = 1.0
        for i in art_rows:
            for j in range(n_cols + 1):
                obj1[j] -= tab[i][j]
        if not pivot(obj1) or obj1[rhs_j] < -1e-7:
            return "infeasible", None
        if feasibility_only:
            return "optimal", None
        # 基中残留取值为 0 的人工变量时，用任一非人工非零列换出
        for i in range(m):
            q = basis[i]
            if q < n + n_slack + n_surp:
                continue
            swapped = False
            for j in range(n + n_slack + n_surp):
                if abs(tab[i][j]) <= LP_EPS:
                    continue
                piv = tab[i][j]
                for jj in range(n_cols + 1):
                    tab[i][jj] /= piv
                for ii in range(m):
                    if ii == i:
                        continue
                    f = tab[ii][j]
                    if abs(f) <= LP_EPS:
                        continue
                    for jj in range(n_cols + 1):
                        tab[ii][jj] -= f * tab[i][jj]
                basis[i] = j
                swapped = True
                break
            if not swapped:
                return "infeasible", None

    # ---- 第二阶段：max c·x ----
    obj2 = [0.0] * (n_cols + 1)
    for j, v in enumerate(c):
        obj2[j] = -v
    for i in range(m):                              # 对当前基规范化目标行
        q = basis[i]
        f = obj2[q]
        if abs(f) <= LP_EPS:
            continue
        for j in range(n_cols + 1):
            obj2[j] -= f * tab[i][j]
    if not pivot(obj2):
        return "unbounded", None

    x = [0.0] * n
    for i, q in enumerate(basis):
        if q < n:
            x[q] = tab[i][rhs_j]
    return "optimal", x


# ==========================================================================
# 入口
# ==========================================================================

def _dev_prefix(k):
    return f"设备 {k + 1}"


def _ov_prefix(k):
    return f"重叠带 {k + 1}（设备 {k + 1}↔{k + 2}）"


def _as_float(v, label, diags, where):
    try:
        f = float(v)
    except (TypeError, ValueError):
        diags.append(f"{where}：{label} 必须是数值（当前 {v!r}）")
        return None
    if f != f or f in (float("inf"), float("-inf")):
        diags.append(f"{where}：{label} 必须是有限数值")
        return None
    return f


def _interp(u, us, vals):
    """单侧实测亮度沿幕布坐标的分段线性插值；超出采样范围按端点平推。"""
    if u <= us[0]:
        return vals[0]
    if u >= us[-1]:
        return vals[-1]
    for i in range(len(us) - 1):
        if us[i] <= u <= us[i + 1]:
            t = (u - us[i]) / (us[i + 1] - us[i])
            return vals[i] + t * (vals[i + 1] - vals[i])
    return vals[-1]


def compute_calibration(segments, device_meas, target, overlap_samples,
                        screen_width):
    """亮度融合校准。

    segments: 与 geometry.compute_blend 相同的区间定义（scheme 含 u0/u1）。
    device_meas: [{base_luminance, attenuation_min, attenuation_max}] × N。
    target:      {luminance, tolerance}（整幅幕布目标亮度与 ±容差）。
    overlap_samples: [[{u,left,right}, …] × (N-1)]，每个相邻重叠带的
                   两侧沿幕布坐标亮度采样（u 为该重叠带内的幕布坐标）。
    screen_width: 整幅幕宽（用于确定两端非重叠可见区）。
    返回校准结果字典。
    """
    n = len(segments)
    Sw = float(screen_width)
    bounds = [(float(s["scheme"]["u0"]), float(s["scheme"]["u1"]))
              for s in segments]
    diags = []

    # ---- 目标亮度与容差 ----
    tgt = target or {}
    T = _as_float(tgt.get("luminance"), "目标亮度", diags, "整幅幕布目标")
    tol = _as_float(tgt.get("tolerance"), "亮度容差", diags, "整幅幕布目标")
    target_ok = True
    if T is None or tol is None:
        target_ok = False
    else:
        if T <= 0:
            diags.append("整幅幕布目标：目标亮度必须为正数")
            target_ok = False
        if tol < 0:
            diags.append("整幅幕布目标：亮度容差不能为负")
            target_ok = False

    # ---- 每台基准亮度 / 衰减上下限 ----
    def pick(container, k):
        if isinstance(container, dict):
            return container.get(str(k), container.get(k))
        return container[k] if k < len(container) else None

    meas = []
    for k in range(n):
        where = _dev_prefix(k)
        m = pick(device_meas, k)
        if not isinstance(m, dict):
            diags.append(f"{where}：缺少实测基准亮度与可调衰减上下限")
            meas.append(None)
            continue
        B = _as_float(m.get("base_luminance"), "实测基准亮度", diags, where)
        lo = _as_float(m.get("attenuation_min"), "衰减下限", diags, where)
        hi = _as_float(m.get("attenuation_max"), "衰减上限", diags, where)
        bad = False
        if B is None or B <= 0:
            if B is not None and B <= 0:
                diags.append(f"{where}：实测基准亮度必须为正数（当前 {B:g}）")
            bad = True
        if lo is not None and not (-LP_EPS <= lo <= 1.0 + LP_EPS):
            diags.append(f"{where}：衰减下限必须在 0~1 之间（1=不衰减，当前 {lo:g}）")
            bad = True
        if hi is not None and not (-LP_EPS <= hi <= 1.0 + LP_EPS):
            diags.append(f"{where}：衰减上限必须在 0~1 之间（1=不衰减，当前 {hi:g}）")
            bad = True
        if lo is not None and hi is not None and lo - hi > LP_EPS:
            diags.append(f"{where}：衰减下限 {lo:g} 大于上限 {hi:g}，可调范围无效")
            bad = True
        if bad:
            meas.append(None)
        else:
            meas.append({"B": B, "lo": min(max(lo, 0.0), 1.0),
                         "hi": min(max(hi, 0.0), 1.0)})

    # ---- 重叠带采样（结构性校验）----
    bands = []
    for k in range(n - 1):
        a, b = bounds[k + 1][0], bounds[k][1]          # [u0_{k+1}, u1_k]
        width = b - a
        band = {"k": k, "a": a, "b": b, "width": width,
                "skipped": width <= EPS, "samples": []}
        where = _ov_prefix(k)
        raw = pick(overlap_samples, k)
        if band["skipped"]:
            if raw:
                diags.append(f"{where}：两区间仅端点相接（融合带宽为 0），无需采样")
            bands.append(band)
            continue
        if not isinstance(raw, list) or not raw:
            diags.append(f"{where}：缺少两侧亮度采样（融合带宽 "
                         f"{max(width, 0.0):.3f}m，至少需要 2 个采样点）")
            bands.append(band)
            continue
        prev_u = None
        ok_count = 0
        allzero = True
        for i, sm in enumerate(raw):
            wwhere = f"{where} 第 {i + 1} 个采样点"
            if not isinstance(sm, dict):
                diags.append(f"{wwhere}：采样格式应为 {{u,left,right}}")
                continue
            u = _as_float(sm.get("u"), "幕布坐标 u", diags, wwhere)
            vl = _as_float(sm.get("left"), "左机亮度", diags, wwhere)
            vr = _as_float(sm.get("right"), "右机亮度", diags, wwhere)
            if None in (u, vl, vr):
                continue
            bad = False
            if vl < -LP_EPS or vr < -LP_EPS:
                diags.append(f"{wwhere}：单侧亮度不能为负（左 {vl:g} / 右 {vr:g}）")
                bad = True
            if u < a - 1e-6 or u > b + 1e-6:
                diags.append(f"{wwhere}：u={u:.3f}m 落在融合带 "
                             f"[{a:.3f}, {b:.3f}]m 之外")
                bad = True
            if prev_u is not None and u <= prev_u + LP_EPS:
                diags.append(f"{wwhere}：采样坐标必须严格递增（u={u:.3f}m "
                             f"与前点重复或倒置）")
                bad = True
            if bad:
                continue
            prev_u = u
            band["samples"].append({"u": u, "left": max(vl, 0.0),
                                    "right": max(vr, 0.0)})
            ok_count += 1
            if vl > 0 or vr > 0:
                allzero = False
        if 0 < ok_count < 2:
            diags.append(f"{where}：至少需要 2 个沿幕布坐标的有效采样点（当前 1 个）")
            band["samples"] = []
        elif ok_count >= 2 and allzero:
            diags.append(f"{where}：全部采样的左右单侧亮度均为 0，无法融合到目标亮度")
            band["samples"] = []
        else:
            band["samples"].sort(key=lambda q: q["u"])
        bands.append(band)

    devices_echo = [
        {"index": k,
         "base_luminance": meas[k]["B"] if meas[k] else None,
         "attenuation_min": meas[k]["lo"] if meas[k] else None,
         "attenuation_max": meas[k]["hi"] if meas[k] else None}
        for k in range(n)]
    overlaps_echo = [_band_echo(bd) for bd in bands]

    if diags:
        return {
            "status": "measurement_invalid",
            "calibrated": False,
            "target": {"luminance": T, "tolerance": tol} if target_ok else None,
            "devices": devices_echo,
            "overlaps": overlaps_echo,
            "attenuations": None,
            "bands": None,
            "predictions": None,
            "diagnostics": diags,
        }

    # ---- 非重叠（独占）可见区间 ----
    # 设备 0 独占 [0, a0]；中间 k 独占 [b_{k-1}, a_k]；末台独占 [b_{n-2}, Sw]
    solo = []
    solo.append((0.0, bands[0]["a"]))
    for k in range(1, n - 1):
        solo.append((bands[k - 1]["b"], bands[k]["a"]))
    solo.append((bands[n - 2]["b"], Sw))

    return _solve(meas, bands, solo, T, tol, Sw,
                  devices_echo, overlaps_echo)


def _band_echo(bd):
    return {
        "between": [bd["k"], bd["k"] + 1],
        "u0": round(bd["a"], 4), "u1": round(bd["b"], 4),
        "width": round(max(bd["width"], 0.0), 4),
        "skipped": bd["skipped"],
        "samples": [{"u": round(q["u"], 4), "left": q["left"],
                     "right": q["right"]} for q in bd["samples"]],
    }


# ==========================================================================
# LP 构建与求解
# ==========================================================================

def _build_rows(meas, bands, solo, T, tol, weights, use_bands=None,
                solo_devices=None, skip_points=None):
    """构建归一化亮度约束。

    变量 x = [g_0..g_{n-1}, s]，s≥0 为归一化公共裕量。
    weights[k]:   第 k 带的左机权重序列（[0]=左端点、其后为各采样点），
                  由调用方给出（已保证从左机到右机单调非增、端点 1→0）。
    use_bands:    参与约束的重叠带序号集合（None=全部）。
    solo_devices: 参与非重叠约束的设备序号集合（None=全部）。
    skip_points:  {(band_idx, sample_idx)} 归因时临时移除的采样点。
    每行 (a, sense, rhs, tag)，tag 标识归属（('solo',k) 或 ('band',k,i)）。
    """
    n = len(meas)
    delta = tol / T
    skip_points = skip_points or set()
    rows = []

    def add(a, sense, rhs, tag):
        rows.append((a, sense, rhs, tag))

    for k, m in enumerate(meas):
        if solo_devices is not None and k not in solo_devices:
            continue
        u0, u1 = solo[k]
        if u1 - u0 <= EPS:
            continue                          # 该台无独占可见区
        c = m["B"] / T
        # c·g ≥ 1-δ+s  →  -c·g + s ≤ -(1-δ)
        a_lo = [0.0] * (n + 1); a_lo[n] = 1.0; a_lo[k] = -c
        # c·g ≤ 1+δ-s  →   c·g + s ≤ 1+δ
        a_hi = [0.0] * (n + 1); a_hi[n] = 1.0; a_hi[k] = c
        add(a_lo, "<=", -(1.0 - delta), ("solo", k))
        add(a_hi, "<=", 1.0 + delta, ("solo", k))

    for bd in bands:
        k = bd["k"]
        if bd["skipped"] or not bd["samples"]:
            continue
        if use_bands is not None and k not in use_bands:
            continue
        ww = weights[k]
        for i, q in enumerate(bd["samples"]):
            if (k, i) in skip_points:
                continue
            w = ww[i + 1]                          # [0]=左端点
            cl = w * q["left"] / T
            cr = (1.0 - w) * q["right"] / T
            a_lo = [0.0] * (n + 1); a_lo[n] = 1.0
            a_hi = [0.0] * (n + 1); a_hi[n] = 1.0
            a_lo[k] = -cl; a_lo[k + 1] = -cr
            a_hi[k] = cl; a_hi[k + 1] = cr
            add(a_lo, "<=", -(1.0 - delta), ("band", k, i))
            add(a_hi, "<=", 1.0 + delta, ("band", k, i))
    return rows


def _feasible(meas, bands, solo, T, tol, weights, use_bands=None,
              solo_devices=None, skip_points=None, with_margin=True):
    """给定权重模式与约束子集是否可行（with_margin=False 允许 s=0，即仅
    要求落在目标容差闭区间内，用于归因判定）。"""
    rows = _build_rows(meas, bands, solo, T, tol, weights,
                       use_bands=use_bands, solo_devices=solo_devices,
                       skip_points=skip_points)
    plain = [(a, sense, rhs) for a, sense, rhs, _ in rows]
    plain.extend(_box_rows(meas, with_margin=with_margin))
    st, _ = simplex([0.0] * (len(meas) + 1), plain, feasibility_only=True)
    return st == "optimal"


def _box_rows(meas, with_margin=True):
    """衰减边界 gmin≤g≤gmax、s≥0 与 s≤1（s 为归一化裕量，物理上不超过
    δ≤1；加上界也避免归因移除约束后 s 无界导致的伪可行）。"""
    n = len(meas)
    rows = []
    for k, m in enumerate(meas):
        e = [0.0] * (n + 1); e[k] = 1.0
        rows.append((e, ">=", m["lo"]))
        rows.append((e, "<=", m["hi"]))
    es = [0.0] * (n + 1); es[n] = 1.0
    rows.append((es, ">=", 0.0 if with_margin else -1e6))
    rows.append((es, "<=", 1.0))
    return rows


def _fallback_g(meas, T):
    """按目标就近夹取的兜底衰减（无共同解时用于标记超差点位）。"""
    out = []
    for m in meas:
        g = T / m["B"] if m["B"] > 0 else 1.0
        out.append(min(max(g, m["lo"]), m["hi"]))
    return out


# ==========================================================================
# 单调渐变权重（保序回归）与联合搜索
# ==========================================================================

def _initial_ramp(kind, m):
    """m 个采样点的左机权重初始模式（不含端点；端点固定 1、0）。"""
    ts = [(i + 1) / (m + 1) for i in range(m)]
    if kind == "linear":
        return [1.0 - t for t in ts]
    if kind == "convex":                    # 左机权重快速下降（凸）
        return [(1.0 - t) ** 1.8 for t in ts]
    if kind == "concave":                   # 左机权重缓慢下降（凹）
        return [1.0 - t ** 1.8 for t in ts]
    if kind == "sigmoid":
        return [1.0 / (1.0 + (t / (1.0 - t)) ** 1.6) if 0 < t < 1 else 1.0 - t
                for t in ts]
    return [1.0 - t for t in ts]


def _fit_weights(bd, g, T):
    """给定两侧实测与当前衰减，求每点“命中目标 T”的理想左机权重，再做
    端点固定为 1→0 的单调非增保序回归（PAVA）。

    理想权重：w* = (T/g_{k+1} - R) / (L - R)（L=w·L·g_k+(1-w)·R·g_{k+1}=T）。
    L==R 时权重无影响，给中性值 0.5。
    """
    k = bd["k"]
    gl, gr = g[k], g[k + 1]
    ideal = []
    for q in bd["samples"]:
        L, R = q["left"] * gl, q["right"] * gr
        if abs(L - R) <= 1e-9:
            ideal.append(0.5)
        else:
            ideal.append(min(1.0, max(0.0, (T - R) / (L - R))))

    # 端点固定（左 1、右 0），对内部点做单调非增 PAVA（池化块均值，块
    # 触碰固定端时以固定值夹持）
    vals = [1.0] + ideal + [0.0]
    n = len(vals)
    fixed = {0: 1.0, n - 1: 0.0}
    blocks = [{"lo": i, "hi": i, "sum": vals[i], "n": 1,
               "fixed": fixed.get(i)} for i in range(n)]
    changed = True
    while changed:
        changed = False
        for i in range(len(blocks) - 1):
            b1, b2 = blocks[i], blocks[i + 1]
            m1 = b1["fixed"] if b1["fixed"] is not None else b1["sum"] / b1["n"]
            m2 = b2["fixed"] if b2["fixed"] is not None else b2["sum"] / b2["n"]
            if m1 >= m2 - 1e-12:
                continue
            if b1["fixed"] is not None and b2["fixed"] is not None:
                break                                     # 1 与 0 不会倒置
            if b1["fixed"] is not None:
                b2["sum"] = m1 * b2["n"]                  # 右块夹到固定值
            elif b2["fixed"] is not None:
                b1["sum"] = m2 * b1["n"]
            else:
                b1["sum"] += b2["sum"]
                b1["n"] += b2["n"]
                b1["hi"] = b2["hi"]
                blocks.pop(i + 1)
            changed = True
            break
    vals2 = [0.0] * n
    for b in blocks:
        val = b["fixed"] if b["fixed"] is not None else b["sum"] / b["n"]
        for j in range(b["lo"], b["hi"] + 1):
            vals2[j] = min(1.0, max(0.0, val))
    return vals2                                            # 含端点


def _point_ok(L, R, gl, gr, w, T, tol):
    """给定两侧亮度、衰减与左机权重，加权结果是否落在目标容差内。"""
    val = w * L * gl + (1.0 - w) * R * gr
    return T - tol - LP_EPS <= val <= T + tol + LP_EPS


def _feasible_range(lumL, lumR, gl, gr, T, tol):
    """w∈[0,1] 中使加权亮度落入 [T-δ,T+δ] 的区间（左端=左机权重）。
    den≈0（两侧加权贡献相同）时可行区间为整个 [0,1] 或空；否则为标量
    方程的两个截点。返回 (lo,hi)；无交集返回 None。"""
    den = lumL * gl - lumR * gr
    if abs(den) <= 1e-12:
        return (0.0, 1.0) if T - tol - LP_EPS <= lumR * gr <= T + tol + LP_EPS else None

    def w_for(target):
        return min(1.0, max(0.0, (target - lumR * gr) / den))

    a, b = w_for(T - tol), w_for(T + tol)
    a, b = min(a, b), max(a, b)
    ok_a = _point_ok(lumL, lumR, gl, gr, a, T, tol)
    ok_b = _point_ok(lumL, lumR, gl, gr, b, T, tol)
    if not ok_a and not ok_b:
        return None
    if not ok_a:
        a = b
    if not ok_b:
        b = a
    return (a, b)


def _smooth_weights(bands, weights, g, T, tol, passes=40):
    """在保持单调（左 1→右 0）与逐点容差可行的前提下，把每点权重向
    线性 ramp 做确定性松弛（二分夹逼），减少保序回归产生的阶跃。"""
    out = {k: list(v) for k, v in weights.items()}
    for bd in bands:
        if bd["skipped"] or not bd["samples"]:
            continue
        k = bd["k"]
        gl, gr = g[k], g[k + 1]
        a, b = bd["a"], bd["b"]
        ww = out[k]
        linear = [1.0] + [(b - q["u"]) / (b - a) for q in bd["samples"]] + [0.0]
        cur = list(ww)
        for _ in range(passes):
            moved = 0.0
            for i in range(1, len(cur) - 1):
                q = bd["samples"][i - 1]
                rng = _feasible_range(q["left"], q["right"], gl, gr, T, tol)
                if rng is None:
                    continue
                lo, hi = rng
                # 单调约束：不小于右侧、不大于左侧
                lo = max(lo, cur[i + 1])
                hi = min(hi, cur[i - 1])
                if lo - hi > 1e-9:
                    continue
                target = linear[i]
                cand = min(hi, max(lo, target))
                # 向线性值走半步，保证确定性收敛
                step = (cand - cur[i]) * 0.5
                nxt = min(hi, max(lo, cur[i] + step))
                moved = max(moved, abs(nxt - cur[i]))
                cur[i] = nxt
            if moved < 1e-7:
                break
        out[k] = cur
    return out


def _weights_from_pattern(bands, patterns):
    """由各带内部权重模式组装含端点的完整权重序列。无采样/零宽的带使用
    线性占位（其约束不会被构建，仅保证按带索引可取）。"""
    out = {}
    for bd in bands:
        k = bd["k"]
        if k in patterns:
            out[k] = [1.0] + list(patterns[k]) + [0.0]
        else:
            a, b = bd["a"], bd["b"]
            us = [q["u"] for q in bd["samples"]]
            ww = [1.0]
            for u in us:
                ww.append((b - u) / (b - a) if b - a > EPS else 0.0)
            ww.append(0.0)
            out[k] = ww
    return out


def _lp_given_weights(meas, bands, solo, T, tol, weights):
    """权重固定时求最大化归一化裕量的衰减。返回 (status, g, s)。"""
    n = len(meas)
    plain = [(a, s, b) for a, s, b, _ in
             _build_rows(meas, bands, solo, T, tol, weights)]
    plain.extend(_box_rows(meas))
    st, x = simplex([0.0] * n + [1.0], plain)
    if st != "optimal":
        return st, None, -1.0
    g = [min(max(x[k], meas[k]["lo"]), meas[k]["hi"]) for k in range(n)]
    return st, g, x[n]


def _joint_search(meas, bands, solo, T, tol):
    """交替搜索：多组确定性初始 ramp × (固定权重求衰减 LP → 固定衰减保序
    拟合权重)，取归一化裕量最大的联合解。返回 (g, weights, s) 或 None。
    """
    active = [bd for bd in bands if not bd["skipped"] and bd["samples"]]
    kinds = ["linear", "convex", "concave", "sigmoid"]
    best = None  # (s, g, weights)

    # 初始衰减：非重叠区命中目标（夹边界）
    g0 = _fallback_g(meas, T)
    if not active:
        # 无融合带（全部零宽相接）：只有非重叠约束，直接解一次
        weights0 = _weights_from_pattern(bands, {})
        st, g, s = _lp_given_weights(meas, bands, solo, T, tol, weights0)
        if st == "optimal" and s >= -LP_EPS:
            return (s, g, weights0)
        return None

    for kind in kinds:
        patterns = {bd["k"]: _initial_ramp(kind, len(bd["samples"]))
                    for bd in active}
        g = list(g0)
        weights = _weights_from_pattern(bands, patterns)
        for it in range(12):
            st, g_new, s = _lp_given_weights(
                meas, bands, solo, T, tol, weights)
            if st == "optimal":
                g = g_new
            # LP 不可行时也用上一轮 g 重新拟合权重（可能通过改变渐变
            # 形状恢复可行）；首轮 g 为非重叠区命中目标的兜底值
            new_patterns = {}
            for bd in active:
                wfull = _fit_weights(bd, g, T)
                new_patterns[bd["k"]] = wfull[1:-1]
            weights_new = _weights_from_pattern(bands, new_patterns)
            moved = max(abs(weights_new[bd["k"]][i] - weights[bd["k"]][i])
                        for bd in active
                        for i in range(len(weights[bd["k"]])))
            weights = weights_new
            if moved < 1e-7:
                st, g, s = _lp_given_weights(
                    meas, bands, solo, T, tol, weights)
                if st == "optimal" and s >= -LP_EPS:
                    if best is None or s > best[0] + 1e-9:
                        best = (s, list(g),
                                {k: list(v) for k, v in weights.items()})
                break
        else:
            st, g, s = _lp_given_weights(
                meas, bands, solo, T, tol, weights)
            if st == "optimal" and s >= -LP_EPS:
                if best is None or s > best[0] + 1e-9:
                    best = (s, list(g),
                            {k: list(v) for k, v in weights.items()})

    if best is None:
        return None
    # 后处理：在不牺牲可行裕量（每个点保留与最优 s 对应的容差带）的前提
    # 下，把阶跃权重平滑为更接近线性 ramp 的单调渐变
    s0, g0b, w0 = best
    sm_tol = tol + s0 * T - 1e-6
    smoothed = _smooth_weights(bands, w0, g0b, T, sm_tol)
    st, g_s, s_s = _lp_given_weights(meas, bands, solo, T, tol, smoothed)
    if st == "optimal" and s_s >= s0 - 1e-7:
        return (s_s, g_s, smoothed)
    return best


def _culprit_diagnosis(meas, bands, solo, T, tol, weights):
    """分组移除复核：定位无共同解的设备 / 具体重叠带超差采样点。

    归因阶段允许公共裕量 s=0（落在容差边界即算可行），找出“移除后恢复
    可行”的设备组/重叠带组，并在致冲突带内逐点定位超差采样。
    """
    active_bands = {bd["k"] for bd in bands
                    if not bd["skipped"] and bd["samples"]}
    messages = []

    def feas(solo_devs, band_set, skip=None):
        return _feasible(meas, bands, solo, T, tol, weights,
                         use_bands=band_set, solo_devices=solo_devs,
                         skip_points=skip, with_margin=False)

    all_solo_devs = {k for k, (u0, u1) in enumerate(solo) if u1 - u0 > EPS}

    # 0) 直接可达区间预检：非重叠区亮度 B·[gmin,gmax] 与目标区间
    #    [T-δ,T+δ] 无交集的设备，无论重叠带权重如何调整都无解
    solo_bad = []
    for k in all_solo_devs:
        m = meas[k]
        lo_L, hi_L = m["lo"] * m["B"], m["hi"] * m["B"]
        if hi_L < T - tol - LP_EPS or lo_L > T + tol + LP_EPS:
            solo_bad.append(k)
    for k in solo_bad:
        m = meas[k]
        lo_L, hi_L = m["lo"] * m["B"], m["hi"] * m["B"]
        messages.append(
            f"{_dev_prefix(k)}：非重叠区在衰减范围 [{m['lo']:.3f}, "
            f"{m['hi']:.3f}] 内的可达亮度为 [{lo_L:.1f}, {hi_L:.1f}] cd/m²，"
            f"与目标 {T:.1f}±{tol:.1f} cd/m² 无交集——衰减范围无共同解")

    # 2) 重叠带：移除整带（保留其余全部，含已点名的 solo 设备）后恢复可行
    band_bad = []
    for k in active_bands:
        if feas(all_solo_devs - set(solo_bad), active_bands - {k}):
            band_bad.append(k)
    for k in band_bad:
        bd = bands[k]
        saved = bd["samples"]
        # 逐点移除（其余重叠带与本带其他点仍在）找出超差采样点
        bad_pts = []
        for i in range(len(saved)):
            if feas(all_solo_devs - set(solo_bad),
                    (active_bands - set(band_bad)) | {k},
                    skip={(k, i)}):
                bad_pts.append(i)
        if not bad_pts:
            bad_pts = list(range(len(saved)))
        pdesc = "、".join(
            f"u={saved[i]['u']:.3f}m（左 {saved[i]['left']:.1f}/"
            f"右 {saved[i]['right']:.1f} cd/m²）" for i in bad_pts)
        messages.append(
            f"{_ov_prefix(k)}：该重叠带采样无法以全局一致衰减与单调渐变权重"
            f"落入目标容差，超差采样点：{pdesc}")

    if not messages:
        messages.append(
            "亮度融合无共同解：各台衰减范围与全部重叠带采样无法同时满足目标"
            "容差（中间设备需以同一个衰减值同时满足左右两个重叠带）")
    return messages


def _solve(meas, bands, solo, T, tol, Sw, devices_echo, overlaps_echo):
    best = _joint_search(meas, bands, solo, T, tol)
    fallback = _fallback_g(meas, T)

    def fail_payload(diags, preds_g=None):
        return {
            "status": "no_common_solution",
            "calibrated": False,
            "target": {"luminance": T, "tolerance": tol,
                       "lower": round(T - tol, 4), "upper": round(T + tol, 4)},
            "devices": devices_echo,
            "overlaps": overlaps_echo,
            "attenuations": None,
            "bands": None,
            "predictions": _predictions(
                meas, bands, solo, Sw,
                preds_g if preds_g is not None else fallback,
                T, tol, best[2] if best else None),
            "margin": 0.0,
            "diagnostics": diags,
        }

    if best is None or best[0] < -1e-9:
        # 用最佳权重（即使无正裕量）做归因复核与超差标记
        w_for_diag = best[2] if best else _weights_from_pattern(
            bands, {bd["k"]: _initial_ramp("linear", len(bd["samples"]))
                    for bd in bands if not bd["skipped"] and bd["samples"]})
        return fail_payload(
            _culprit_diagnosis(meas, bands, solo, T, tol, w_for_diag),
            preds_g=best[1] if best else None)

    s, g, weights = best
    margin = max(s, 0.0) * T
    preds = _predictions(meas, bands, solo, Sw, g, T, tol, weights)
    if preds["out_of_tolerance"]:
        return fail_payload(
            _culprit_diagnosis(meas, bands, solo, T, tol, weights), preds_g=g)

    atts = [{
        "index": k,
        "attenuation": round(g[k], 4),
        "output_luminance": round(meas[k]["B"] * g[k], 2),
    } for k in range(len(meas))]
    return {
        "status": "ok",
        "calibrated": True,
        "target": {"luminance": T, "tolerance": tol,
                   "lower": round(T - tol, 4), "upper": round(T + tol, 4)},
        "devices": devices_echo,
        "overlaps": overlaps_echo,
        "attenuations": atts,
        "bands": [_band_output(bd, weights) for bd in bands],
        "predictions": preds,
        "margin": round(margin, 4),
        "diagnostics": [],
    }


def _band_output(bd, weights):
    """单个重叠带的端点/采样点权重输出（weights 含端点的左机权重序列）。"""
    base = _band_echo(bd)
    if bd["skipped"]:
        base["weights"] = None
        base["skipped"] = True
        return base
    ww = weights[bd["k"]]
    a, b = bd["a"], bd["b"]
    us = [q["u"] for q in bd["samples"]]
    pts = [{"u": round(a, 4), "w_left": 1.0, "w_right": 0.0,
            "endpoint": "left"}]
    for i, u in enumerate(us):
        w = ww[i + 1]
        pts.append({"u": round(u, 4), "w_left": round(w, 4),
                    "w_right": round(1.0 - w, 4), "endpoint": None})
    pts.append({"u": round(b, 4), "w_left": 0.0, "w_right": 1.0,
                "endpoint": "right"})
    base["weights"] = pts
    base["skipped"] = False
    return base


def _predictions(meas, bands, solo, Sw, g, T, tol, weights=None):
    """逐点预测亮度：非重叠区代表点 + 各重叠带端点与采样点。

    weights 为 None（无解兜底）时各带按线性 ramp 计算，仅用于标记超差采样。
    """
    points = []

    def rec(u, L, region, between=None, measured=None,
            w_left=None, endpoint=None):
        d = {
            "u": round(u, 4),
            "luminance": round(L, 2),
            "within_tolerance": T - tol - LP_EPS <= L <= T + tol + LP_EPS,
            "region": region,
        }
        if between is not None:
            d["between"] = list(between)
        if measured is not None:
            d["measured"] = round(measured, 2)
            d["measured_out_of_tolerance"] = \
                not (T - tol - LP_EPS <= measured <= T + tol + LP_EPS)
        if w_left is not None:
            d["w_left"] = round(w_left, 4)
            d["w_right"] = round(1.0 - w_left, 4)
        if endpoint is not None:
            d["endpoint"] = endpoint
        points.append(d)

    # 非重叠（独占）区：取幕布可见部分的中点
    for k, (u0, u1) in enumerate(solo):
        v0, v1 = max(u0, 0.0), min(u1, Sw)
        if v1 - v0 <= EPS:
            continue
        rec((v0 + v1) / 2, meas[k]["B"] * g[k], "solo", between=(k, k))

    for bd in bands:
        if bd["skipped"]:
            continue
        k = bd["k"]
        a, b = bd["a"], bd["b"]
        width = b - a
        us = [q["u"] for q in bd["samples"]]
        left = [q["left"] for q in bd["samples"]]
        right = [q["right"] for q in bd["samples"]]
        ww = weights[bd["k"]] if weights else None  # [左端, 采样…, 右端]

        def w_linear(u):
            return (b - u) / width

        def lum(u, idx=None):
            # idx: 0=左端点，1..m=采样点，m+1=右端点
            w = ww[idx] if ww is not None else w_linear(u)
            Bl, Br = _interp(u, us, left), _interp(u, us, right)
            return (w * Bl * g[k] + (1.0 - w) * Br * g[k + 1], w,
                    w * Bl + (1.0 - w) * Br)

        La, wa, _ = lum(a, 0)
        rec(a, La, "overlap", between=(k, k + 1), w_left=wa, endpoint="left")
        for i, u in enumerate(us):
            L, w, raw = lum(u, i + 1)
            rec(u, L, "overlap", between=(k, k + 1), measured=raw, w_left=w)
        Lb, wb, _ = lum(b, len(us) + 1)
        rec(b, Lb, "overlap", between=(k, k + 1), w_left=wb, endpoint="right")

    out_of_tol = [i for i, p in enumerate(points)
                  if not p["within_tolerance"]]
    return {"points": points, "out_of_tolerance": out_of_tol}
