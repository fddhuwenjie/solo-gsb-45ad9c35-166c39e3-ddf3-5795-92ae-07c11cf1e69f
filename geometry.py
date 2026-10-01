"""投影机选位几何计算核心。

坐标约定（顶视图）：房间左上角为原点，x 轴向右，y 轴由幕布墙指向后墙，单位米。
幕布安装在 y=0 的前墙上，中心 x 坐标为 screen["cx"]。
投影机镜头位置记为 (px, py)，镜头位于机身前表面中央，
因此机身占据矩形 [px-bw/2, px+bw/2] × [py, py+bd]。

每个镜头方案的可安装区域 = 以下约束的交集：
  1. 投射距离：py ∈ [tr_min*Sw, tr_max*Sw]
  2. 镜头水平位移：px ∈ [cx-hs, cx+hs]
  3. 墙面余量：机身矩形不得越出四墙内缩 margin 的范围
  4. 机身避障：机身矩形不得与任何禁装区相交
交集为空时给出导致为空的约束诊断。

退化可行域（安装线）：水平镜头位移为 0（或位移带被墙面余量夹成单点）
时，px 固定为某一 x，可安装区域退化为一条纵深线段。只要线段长度大于 0
即可沿纵深安放机身，因此线段同样视为可行域（面积为 0 但 line_length > 0）。
此时禁装区仍按机身尺寸膨胀，仅当膨胀后的 x 区间覆盖该固定 x（含严格内点，
边界接触不算碰撞），才把其 y 区间投影为纵深禁段从安装线上扣除；线段被全部
覆盖时才给出避障无解诊断。
"""

EPS = 1e-9


def rect_w(r):
    return max(0.0, r[2] - r[0])


def rect_h(r):
    return max(0.0, r[3] - r[1])


def rect_area(r):
    return rect_w(r) * rect_h(r)


def rects_intersect(a, b):
    return (min(a[2], b[2]) - max(a[0], b[0]) > EPS and
            min(a[3], b[3]) - max(a[1], b[1]) > EPS)


def interval_hit(a, b, lo, hi):
    """开区间式重叠判定：区间 (a,b) 与 (lo,hi) 是否有严格大于 EPS 的重叠。
    边界接触（端点相等或间隙 ≤ EPS）不算命中，与矩形扣除的接触规则一致。
    当 a==b（固定 x 的安装线退化为点）时按严格包含判定。"""
    if abs(b - a) <= EPS:
        return lo + EPS < a < hi - EPS
    return min(b, hi) - max(a, lo) > EPS


def subtract_interval(seg, lo, hi):
    """从纵深线段 seg=(a,b) 中扣除禁段 (lo,hi)，返回剩余线段。
    与 subtract_rect 的接触规则一致：禁段与线段无内部重叠（间隙 ≤ EPS 或
    仅在端点相接）时不扣；严格进入线段内部才切除；切除后剩余碎段
    长度 ≤ EPS 时丢弃（仅余单个接触点即视为该线段被完全覆盖）。"""
    a, b = seg
    ia, ib = max(a, lo), min(b, hi)
    if ib - ia <= EPS:
        return [tuple(seg)]
    out = []
    if ia - a > EPS:
        out.append((a, ia))
    if b - ib > EPS:
        out.append((ib, b))
    return out


def subtract_rect(rect, hole):
    """从 rect 中减去 hole，返回 0~4 个互不重叠的矩形（用于禁装区扣除）。"""
    x1, y1, x2, y2 = rect
    hx1, hy1, hx2, hy2 = hole
    ix1, iy1 = max(x1, hx1), max(y1, hy1)
    ix2, iy2 = min(x2, hx2), min(y2, hy2)
    if ix1 >= ix2 - EPS or iy1 >= iy2 - EPS:
        return [list(rect)]
    out = []
    if ix1 - x1 > EPS:
        out.append([x1, y1, ix1, y2])          # 左条
    if x2 - ix2 > EPS:
        out.append([ix2, y1, x2, y2])          # 右条
    if iy1 - y1 > EPS:
        out.append([ix1, y1, ix2, iy1])        # 上条
    if y2 - iy2 > EPS:
        out.append([ix1, iy2, ix2, y2])        # 下条
    return out


def _derive(room, screen, scheme):
    """汇总方案派生量。"""
    sw, sh = screen["width"], screen["height"]
    return {
        "W": room["width"], "D": room["depth"], "H": room["height"],
        "m": room.get("margin", 0.0),
        "Sw": sw, "Sh": sh,
        "cx": screen["cx"], "sb": screen["bottom"],
        "sc": screen["bottom"] + sh / 2.0,               # 幕布中心高度
        "bw": scheme["body_w"], "bd": scheme["body_d"], "bh": scheme["body_h"],
        "d_min": scheme["tr_min"] * sw,                  # 最近投射距离
        "d_max": scheme["tr_max"] * sw,                  # 最远投射距离
        "hs": scheme["h_shift"] * sw,                    # 水平位移半宽（米）
        "vs": scheme["v_shift"] * sh,                    # 垂直位移半高（米）
    }


def _obstacle_rect(ob):
    return [ob["x"], ob["y"], ob["x"] + ob["w"], ob["y"] + ob["h"]]


def compute_scheme(room, screen, scheme, obstacles, point=None, lens_height=None,
                   clearance=0.0):
    """计算单个方案的可安装区域（公开接口，结果数值保留 4 位小数）。"""
    raw = _compute_scheme_raw(room, screen, scheme, obstacles, point, lens_height,
                              clearance)
    return _serialize_device(raw)


def _serialize_device(raw):
    """把内部浮点结果整理为对外 JSON 结构（与单机接口字段保持一致）。"""
    out = dict(raw)
    out["area"] = round(raw["area"], 4)
    out["line_length"] = round(raw["line_length"], 4)
    out["base_rect"] = [round(v, 4) for v in raw["base_rect"]] if raw["base_rect"] else None
    out["region"] = [[round(v, 4) for v in r] for r in raw["region"]]
    rng = raw["ranges"]
    out["ranges"] = {
        "x": [round(v, 4) for v in rng["x"]] if rng["x"] else None,
        "y": [round(v, 4) for v in rng["y"]] if rng["y"] else None,
        "z": [round(v, 4) for v in rng["z"]] if rng["z"] else None,
        "throw": [round(v, 4) for v in rng["throw"]],
        "shift_x": [round(v, 4) for v in rng["shift_x"]],
        "shift_z": [round(v, 4) for v in rng["shift_z"]],
    }
    dv = raw["derived"]
    out["derived"] = {k: round(v, 4) for k, v in dv.items()}
    return out


def _compute_scheme_raw(room, screen, scheme, obstacles, point=None, lens_height=None,
                        clearance=0.0):
    """计算单个方案的可安装区域、面积、诊断与选点校验（内部浮点结果）。

    clearance 为机身检修净距（米）：禁装区按“机身四周再外扩 clearance 后的
    检修包络”膨胀扣除；多机拼接时逐机调用，保证检修包络不进禁装区。
    """
    g = _derive(room, screen, scheme)
    W, D, H, m = g["W"], g["D"], g["H"], g["m"]
    cx, hs, sc, vs = g["cx"], g["hs"], g["sc"], g["vs"]
    bw, bd, bh = g["bw"], g["bd"], g["bh"]
    d_min, d_max = g["d_min"], g["d_max"]

    diags = []

    # ---- 各约束区间 ----
    wall_x = (m + bw / 2, W - m - bw / 2)     # 墙面余量（水平，机身不越界）
    shift_x = (cx - hs, cx + hs)              # 镜头水平位移
    wall_y = (m, D - m - bd)                  # 墙面余量（纵深，机身在镜头后方）
    throw_y = (d_min, d_max)                  # 投射距离
    fit_z = (bh / 2, H - bh / 2)              # 机身不穿出地板/天花板
    shift_z = (sc - vs, sc + vs)              # 镜头垂直位移

    x_rng = (max(wall_x[0], shift_x[0]), min(wall_x[1], shift_x[1]))
    y_rng = (max(wall_y[0], throw_y[0]), min(wall_y[1], throw_y[1]))
    z_rng = (max(fit_z[0], shift_z[0]), min(fit_z[1], shift_z[1]))

    x_ok = x_rng[1] - x_rng[0] > -EPS
    y_ok = y_rng[1] - y_rng[0] > -EPS
    z_ok = z_rng[1] - z_rng[0] > -EPS

    # ---- 交集为空时定位元凶约束 ----
    if not x_ok:
        if wall_x[1] < wall_x[0]:
            diags.append(
                f"墙面余量约束不可满足：机身宽 {bw:.2f}m + 两侧余量 {2 * m:.2f}m "
                f"超过房间宽 {W:.2f}m")
        elif shift_x[0] > wall_x[1]:
            diags.append(
                f"镜头水平位移与墙面余量冲突：幕布中心偏右（cx={cx:.2f}m），"
                f"位移仅 ±{hs:.2f}m，机身无法避开右墙余量")
        elif shift_x[1] < wall_x[0]:
            diags.append(
                f"镜头水平位移与墙面余量冲突：幕布中心偏左（cx={cx:.2f}m），"
                f"位移仅 ±{hs:.2f}m，机身无法避开左墙余量")
        else:
            diags.append("镜头水平位移范围与墙面余量范围无交集")
    if not y_ok:
        if wall_y[1] < wall_y[0]:
            diags.append(
                f"墙面余量约束不可满足：机深 {bd:.2f}m + 前后余量 {2 * m:.2f}m "
                f"超过房间进深 {D:.2f}m")
        elif throw_y[0] > wall_y[1]:
            diags.append(
                f"投射距离与墙面余量冲突：最小投射距离 {throw_y[0]:.2f}m "
                f"大于可用进深 {wall_y[1]:.2f}m（投射比过大或房间太浅）")
        elif throw_y[1] < wall_y[0]:
            diags.append(
                f"投射距离与墙面余量冲突：最大投射距离 {throw_y[1]:.2f}m "
                f"小于前墙余量 {wall_y[0]:.2f}m")
        else:
            diags.append("投射距离范围与墙面余量范围无交集")
    if not z_ok:
        if fit_z[1] < fit_z[0]:
            diags.append(f"房间净高 {H:.2f}m 容不下机身高 {bh:.2f}m")
        elif shift_z[0] > fit_z[1]:
            diags.append(
                f"镜头垂直位移与房间净高冲突：幕布中心 {sc:.2f}m 过高且向下位移 "
                f"仅 {vs:.2f}m，机身将顶到天花板")
        elif shift_z[1] < fit_z[0]:
            diags.append(
                f"镜头垂直位移与地板冲突：幕布中心 {sc:.2f}m 过低且向上位移 "
                f"仅 {vs:.2f}m，机身将触地")
        else:
            diags.append("镜头垂直位移范围与房间净高范围无交集")

    # ---- 顶视图可安装区域 = 基础矩形 − 各禁装区（按机身尺寸膨胀）----
    # x 区间退化为单点时，可行域是固定 x 的一条纵深安装线（面积为 0 但长度可 > 0）
    base_rect = None
    region = []
    area = 0.0
    line_length = 0.0
    domain = "empty"
    if x_ok and y_ok:
        base_rect = [x_rng[0], y_rng[0], x_rng[1], y_rng[1]]
        # 检修净距：镜头可行域需让“机身矩形四周再外扩 clearance 的检修包络”
        # 不进禁装区，故禁装区在原有按机身尺寸膨胀基础上四周再外扩 clearance
        expanded = [[ob["x"] - bw / 2 - clearance, ob["y"] - bd - clearance,
                     ob["x"] + ob["w"] + bw / 2 + clearance,
                     ob["y"] + ob["h"] + clearance]
                    for ob in obstacles]
        if rect_h(base_rect) <= EPS:
            # 纵深也退化为点：线长为 0，无法安放机身
            region = [list(base_rect)]
            if rect_w(base_rect) <= EPS:
                diags.append("可安装区域退化为点（水平位移与投射距离均无余量），实际无法安放机身")
            else:
                diags.append("可安装区域退化为无纵深的条带（投射距离无余量），实际无法安放机身")
        elif rect_w(base_rect) <= EPS:
            # ---- 退化可行域：固定 x 的安装线 ----
            x0 = x_rng[0]
            domain = "line"
            segs = [(y_rng[0], y_rng[1])]
            hit_idx = []
            for i, exp in enumerate(expanded):
                # 固定 x 被膨胀禁装区的 x 区间严格覆盖（边界接触不算）才需要扣除
                if not interval_hit(x0, x0, exp[0], exp[2]):
                    continue
                hit_idx.append(i)
                nxt = []
                for seg in segs:
                    nxt.extend(subtract_interval(seg, exp[1], exp[3]))
                segs = nxt
            line_length = sum(b - a for a, b in segs)
            region = [[x0, a, x0, b] for a, b in segs]
            if line_length <= EPS and hit_idx:
                # 逐一移除禁装区做恢复测试，找出覆盖整条安装线的元凶
                names = []
                for i in hit_idx:
                    rest = [(y_rng[0], y_rng[1])]
                    for j in hit_idx:
                        if i == j:
                            continue
                        nxt = []
                        for seg in rest:
                            nxt.extend(subtract_interval(seg, expanded[j][1], expanded[j][3]))
                        rest = nxt
                    if sum(b - a for a, b in rest) > EPS:
                        names.append(obstacles[i].get("name") or f"#{i + 1}")
                if names:
                    diags.append("机身避障约束不可满足：禁装区 " +
                                 "、".join(f"「{n}」" for n in names) +
                                 " 完全覆盖了安装线段")
                else:
                    diags.append("机身避障约束不可满足：多个禁装区组合完全覆盖了安装线段")
        else:
            # ---- 普通二维可安装区域 ----
            domain = "area"
            region = [list(base_rect)]
            for exp in expanded:
                nxt = []
                for r in region:
                    nxt.extend(subtract_rect(r, exp))
                region = nxt
            area = sum(rect_area(r) for r in region)
            if area <= EPS:
                # 逐一移除禁装区做恢复测试，找出覆盖可安装区域的元凶
                names = []
                for i, exp in enumerate(expanded):
                    if not rects_intersect(base_rect, exp):
                        continue
                    rest = [list(base_rect)]
                    for j, exp2 in enumerate(expanded):
                        if i == j:
                            continue
                        nxt = []
                        for r in rest:
                            nxt.extend(subtract_rect(r, exp2))
                        rest = nxt
                    if sum(rect_area(r) for r in rest) > EPS:
                        names.append(obstacles[i].get("name") or f"#{i + 1}")
                if names:
                    diags.append("机身避障约束不可满足：禁装区 " +
                                 "、".join(f"「{n}」" for n in names) +
                                 " 完全覆盖了可安装区域")
                else:
                    diags.append("机身避障约束不可满足：多个禁装区组合完全覆盖了可安装区域")

    # ---- 当前选点校验 ----
    pt = None
    if point is not None:
        px, py = point["x"], point["y"]
        hz = lens_height if lens_height is not None else sc
        # 选点避障按检修包络（机身四周外扩 clearance）判定
        body_clear = [px - bw / 2 - clearance, py - clearance,
                      px + bw / 2 + clearance, py + bd + clearance]
        ob_hit = None
        for i, ob in enumerate(obstacles):
            if rects_intersect(body_clear, _obstacle_rect(ob)):
                ob_hit = ob.get("name") or f"#{i + 1}"
                break
        checks = {
            "throw": throw_y[0] - EPS <= py <= throw_y[1] + EPS,
            "shift": shift_x[0] - EPS <= px <= shift_x[1] + EPS,
            "wall": (wall_x[0] - EPS <= px <= wall_x[1] + EPS and
                     wall_y[0] - EPS <= py and py + bd <= D - m + EPS),
            "obstacle": ob_hit is None,
            "height": bool(z_ok) and z_rng[0] - EPS <= hz <= z_rng[1] + EPS,
        }
        pt = {
            "x": px, "y": py, "z": hz,
            "ok": all(checks.values()),
            "checks": checks,
            "obstacle_hit": ob_hit,
            "throw_distance": py,
            "throw_ratio": py / g["Sw"] if g["Sw"] else 0.0,
            "h_shift_used": (px - cx) / g["Sw"] if g["Sw"] else 0.0,
            "v_shift_used": (hz - sc) / g["Sh"] if g["Sh"] else 0.0,
        }

    feasible = bool(x_ok and y_ok and z_ok and
                    (area > EPS or line_length > EPS))
    return {
        "id": scheme.get("id"),
        "name": scheme.get("name", "方案"),
        "feasible": feasible,
        "domain": domain,
        "area": area,
        "line_length": line_length,
        "base_rect": list(base_rect) if base_rect else None,
        "region": [list(r) for r in region],
        "diagnostics": diags,
        "ranges": {
            "x": list(x_rng) if x_ok else None,
            "y": list(y_rng) if y_ok else None,
            "z": list(z_rng) if z_ok else None,
            "throw": [d_min, d_max],
            "shift_x": list(shift_x),
            "shift_z": list(shift_z),
        },
        "derived": {
            "d_min": d_min, "d_max": d_max,
            "hs": hs, "vs": vs, "sc": sc,
        },
        "point": pt,
    }


# ==========================================================================
# 多机拼接规划
#
# 用户把同一幅幕布划成 N（2~3）个有序覆盖区间 seg_k=(u0,u1)（幕布坐标，
# 单位米，允许越出幕布边缘）。第 k 台投影机按“虚拟幕布”参与单机求解：
#   区间宽度  Wk = u1-u0   替代整幅幕宽参与投射比计算
#   区间中心 Ck = (u0+u1)/2 决定水平位移带（幕布整体 cx 平移到 cx-Cs+Ck）
# 垂直方向（幕高、下沿、垂直位移）沿用整幅幕布。
#
# 覆盖约束：
#   ① 区间从左到右有序且宽度为正；
#   ② 连续覆盖整幅幕布：u0_0 ≤ 幕左沿、u1_{N-1} ≥ 幕右沿、相邻无缝
#      （u0_{k+1} ≤ u1_k，留缝即不能连续覆盖）；
#   ③ 邻接重叠 o_k = u1_k - u0_{k+1} 不得小于双方要求的最大值
#      max(min_overlap_k, min_overlap_{k+1})。
#
# 机身检修包络（顶视图）：机身矩形 [px-bw/2, px+bw/2] × [py, py+bd]
# 四周再外扩 clearance_k。包络彼此之间、与禁装区之间均不得相交
# （边界接触允许，与单机扣除的接触规则一致）。
# ==========================================================================

BLEND_MIN = 2
BLEND_MAX = 3


def _seg_screen(screen, cx0, u0, u1):
    """由覆盖区间构造第 k 台的虚拟幕布：宽度=区间宽，中心随区间中心平移。"""
    half = screen["width"] / 2.0
    cs = cx0 - half                         # 整幅幕布左沿
    w = u1 - u0
    return {
        "width": w,
        "height": screen["height"],
        "bottom": screen["bottom"],
        "cx": cs + (u0 + u1) / 2.0,         # 区间中心的房间 x 坐标
    }


def service_envelope(px, py, bw, bd, clearance):
    """镜头点 (px,py) 处机身四周外扩检修净距后的检修包络矩形。"""
    return [px - bw / 2 - clearance, py - clearance,
            px + bw / 2 + clearance, py + bd + clearance]


def _envelope_forbidden_box(point_a, dev_a, dev_k):
    """已定位的 a 的检修包络对待定位 k 的镜头点构成的禁置矩形。

    a 的包络 E_a 与 k 的包络 E_k 相交，等价于 k 的镜头点落在
    E_a 按 (bw_k/2+cl_k, 0, bw_k/2+cl_k, bd_k+cl_k) 膨胀后的矩形内。
    """
    ex1, ey1, ex2, ey2 = service_envelope(
        point_a["x"], point_a["y"], dev_a["bw"], dev_a["bd"], dev_a["clearance"])
    hx = dev_k["bw"] / 2 + dev_k["clearance"]
    return [ex1 - hx, ey1 - dev_k["bd"] - dev_k["clearance"],
            ex2 + hx, ey2 + dev_k["clearance"]]


def _tidy_area(rects):
    """丢弃退化碎矩形（宽或高 ≤ EPS）。"""
    return [r for r in rects if rect_w(r) > EPS and rect_h(r) > EPS]


def _residual(dev, boxes):
    """逐机可行域扣除若干镜头点禁置矩形后的剩余可行域。"""
    if dev["domain"] == "line":
        segs = [tuple(s) for s in dev["segs"]]
        x0 = dev["line_x"]
        for box in boxes:
            if not interval_hit(x0, x0, box[0], box[2]):
                continue
            nxt = []
            for seg in segs:
                nxt.extend(subtract_interval(seg, box[1], box[3]))
            segs = [(a, b) for a, b in nxt if b - a > EPS]
        return {"domain": "line", "x": x0, "segs": segs}
    rects = [list(r) for r in dev["region"]]
    for box in boxes:
        nxt = []
        for r in rects:
            nxt.extend(subtract_rect(r, box))
        rects = _tidy_area(nxt)
    return {"domain": "area", "rects": rects}


def _residual_nonempty(res):
    if res["domain"] == "line":
        return any(b - a > EPS for a, b in res["segs"])
    return len(res["rects"]) > 0


def _in_residual(p, res):
    """镜头点是否位于剩余可行域内。"""
    x, y = p["x"], p["y"]
    if res["domain"] == "line":
        if abs(x - res["x"]) > EPS:
            return False
        return any(a - EPS <= y <= b + EPS for a, b in res["segs"])
    return any(r[0] - EPS <= x <= r[2] + EPS and r[1] - EPS <= y <= r[3] + EPS
               for r in res["rects"])


def _candidates_for(dev, res, want, limit=16):
    """从剩余可行域生成候选镜头点；want 点（用户拖动中）优先但需在剩余域内。"""
    pts = []
    seen = set()

    def add(x, y):
        key = (round(x, 6), round(y, 6))
        if key not in seen:
            seen.add(key)
            pts.append({"x": x, "y": y})

    if want is not None and _in_residual(want, res):
        add(want["x"], want["y"])
    if res["domain"] == "line":
        x0 = res["x"]
        for (a, b) in res["segs"]:
            add(x0, (a + b) * 0.5)
            add(x0, a + 1e-6)
            add(x0, b - 1e-6)
    else:
        rects = sorted(res["rects"], key=rect_area, reverse=True)
        for r in rects[:3]:
            x1, y1, x2, y2 = r
            for fy in (0.5, 0.25, 0.75):
                for fx in (0.5, 0.2, 0.8):
                    add(x1 + fx * (x2 - x1), y1 + fy * (y2 - y1))
        for r in rects[3:]:
            add((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)

    return [p for p in pts if _in_residual(p, res)][:limit]


def _solve_joint(devs, wants=None):
    """在逐机可行域内求一组检修包络两两不相交的安装点。

    DFS：逐台把“已定位设备的包络对本台镜头点的禁置矩形”从其可行域中
    精确扣除，在剩余域上取候选点；每台都能定位即成功。
    wants[k] 为用户当前点（若有），作为第 k 台首选候选，优先贴合交互状态。
    返回 {points: [...], status: "ok"|"joint_infeasible"}。
    """
    n = len(devs)
    wants = wants or [None] * n
    order = sorted(range(n),
                   key=lambda k: 0 if devs[k]["domain"] == "line" else 1)
    points = [None] * n

    def dfs(depth, placed):
        if depth == n:
            return True
        k = order[depth]
        boxes = [_envelope_forbidden_box(placed[a], devs[a], devs[k])
                 for a in placed]
        res = _residual(devs[k], boxes)
        if not _residual_nonempty(res):
            return False
        for cand in _candidates_for(devs[k], res, wants[k]):
            points[k] = cand
            placed[k] = cand
            if dfs(depth + 1, placed):
                return True
            del placed[k]
        points[k] = None
        return False

    if dfs(0, {}):
        return {"status": "ok", "points": points}
    return {"status": "joint_infeasible", "points": [None] * n}


def _grid_feasible_pair(dev_a, dev_b, n=7):
    """栅格采样快速判断两台是否存在兼容点对（用于两两冲突诊断）。"""
    def grid(dev):
        if dev["domain"] == "line":
            out = []
            for (a, b) in dev["segs"]:
                for t in range(n):
                    y = a + (b - a) * t / max(1, n - 1)
                    out.append({"x": dev["line_x"], "y": y})
            return out
        out = []
        for r in dev["region"]:
            for i in range(n):
                for j in range(n):
                    out.append({"x": r[0] + (r[2] - r[0]) * (i + 0.5) / n,
                                "y": r[1] + (r[3] - r[1]) * (j + 0.5) / n})
        return out

    pa, pb = grid(dev_a), grid(dev_b)
    for a in pa:
        ea = service_envelope(a["x"], a["y"], dev_a["bw"], dev_a["bd"],
                              dev_a["clearance"])
        for b in pb:
            eb = service_envelope(b["x"], b["y"], dev_b["bw"], dev_b["bd"],
                                  dev_b["clearance"])
            if not rects_intersect(ea, eb):
                return True
    return False


def _round_rect(r):
    return [round(v, 4) for v in r]


def compute_blend(room, screen, segments, obstacles, points=None, lens_heights=None):
    """多机拼接规划联合求解。

    segments: [{scheme, min_overlap, clearance}], 顺序即从左到右的覆盖区间，
              每个 scheme 需含 u0,u1（覆盖区间端点，幕布坐标：0=幕左沿，
              Sw=幕右沿；可越界）及单机镜头参数。
    points:   [{x,y}] × N 或 None，用户当前安装点，用于校验与作为求解首选。
    lens_heights: [float] × N 或 None。
    返回联合状态、每台单机结果（含区间信息）与诊断。
    """
    n = len(segments)
    points = points or [None] * n
    lens_heights = lens_heights or [None] * n
    Sw = screen["width"]
    cx0 = screen["cx"]
    left, right = 0.0, Sw

    # ---- 覆盖区间校验（参数级）----
    interval_diags = []
    valid_bounds = []
    for k, seg in enumerate(segments):
        u0, u1 = seg["scheme"]["u0"], seg["scheme"]["u1"]
        valid_bounds.append((u0, u1))
        if u1 - u0 <= EPS:
            interval_diags.append(
                f"设备 {k + 1} 的覆盖区间宽度必须为正（当前区间 "
                f"[{u0:.2f}, {u1:.2f}]m）")
    # 从左到右有序（不交叉嵌套）
    ordered_ok = True
    for k in range(1, n):
        if valid_bounds[k][0] < valid_bounds[k - 1][0] - EPS or \
                valid_bounds[k][1] < valid_bounds[k - 1][1] - EPS:
            ordered_ok = False
    if not ordered_ok:
        interval_diags.append(
            "覆盖区间未按从左到右有序排列（出现交叉或嵌套），请检查各区间起止")
    # 连续覆盖整幅幕布
    if all(u1 - u0 > EPS for u0, u1 in valid_bounds):
        if valid_bounds[0][0] > left + EPS:
            interval_diags.append(
                f"第 1 个区间起点 {valid_bounds[0][0]:.2f}m 未覆盖幕布左沿 0.00m，"
                f"左端留有 {valid_bounds[0][0]:.2f}m 未覆盖")
        if valid_bounds[-1][1] < right - EPS:
            interval_diags.append(
                f"最后区间终点 {valid_bounds[-1][1]:.2f}m 未覆盖幕布右沿 "
                f"{Sw:.2f}m，右端留有 {Sw - valid_bounds[-1][1]:.2f}m 未覆盖")
        for k in range(1, n):
            gap = valid_bounds[k][0] - valid_bounds[k - 1][1]
            if gap > EPS:
                interval_diags.append(
                    f"设备 {k} 与设备 {k + 1} 的区间之间留有 {gap:.2f}m 缝隙，"
                    f"不能连续覆盖整幅幕布")
    # 邻接重叠不小于要求（取双方要求的最大值）
    overlaps = []
    for k in range(1, n):
        ov = valid_bounds[k - 1][1] - valid_bounds[k][0]
        need = max(float(segments[k - 1].get("min_overlap", 0.0)),
                   float(segments[k].get("min_overlap", 0.0)))
        overlaps.append((ov, need))
        if ov > -EPS and ov + EPS < need:
            # 存在缝隙时已在上面报“未连续覆盖”，这里仅报告重叠不足
            interval_diags.append(
                f"设备 {k} 与设备 {k + 1} 的邻接重叠仅 {max(ov, 0):.2f}m，"
                f"小于最小拼接重叠 {need:.2f}m")

    # ---- 逐机单机求解（区间宽度替代整幅幕宽、区间中心决定水平位移）----
    devs = []
    device_results = []
    for k, seg in enumerate(segments):
        sch = seg["scheme"]
        u0, u1 = sch["u0"], sch["u1"]
        vscreen = _seg_screen(screen, cx0, u0, u1)
        raw = _compute_scheme_raw(
            room, vscreen, sch, obstacles,
            point=points[k], lens_height=lens_heights[k],
            clearance=float(seg.get("clearance", 0.0)))
        res = _serialize_device(raw)
        res["segment_index"] = k
        res["segment"] = {"u0": round(u0, 4), "u1": round(u1, 4),
                          "width": round(u1 - u0, 4),
                          "center": round((u0 + u1) / 2, 4),
                          "min_overlap": round(float(seg.get("min_overlap", 0.0)), 4),
                          "clearance": round(float(seg.get("clearance", 0.0)), 4)}
        if k < len(overlaps):
            res["segment"]["overlap_right"] = round(overlaps[k][0], 4)
            res["segment"]["overlap_required"] = round(overlaps[k][1], 4)
        device_results.append(res)

        bw, bd = sch["body_w"], sch["body_d"]
        cl = float(seg.get("clearance", 0.0))
        if raw["domain"] == "line":
            segs = [(r[1], r[3]) for r in raw["region"] if r[3] - r[1] > EPS]
            line_x = raw["base_rect"][0] if raw["base_rect"] else vscreen["cx"]
            devs.append({"domain": "line", "region": raw["region"],
                         "segs": segs, "line_x": line_x,
                         "bw": bw, "bd": bd, "clearance": cl})
        else:
            devs.append({"domain": raw["domain"], "region": raw["region"],
                         "bw": bw, "bd": bd, "clearance": cl})

    # ---- 设备无解 ----
    infeasible_idx = [k for k, r in enumerate(device_results) if not r["feasible"]]

    # ---- 联合状态 ----
    joint_diags = list(interval_diags)
    suggested = [None] * n
    status = "ok"

    if interval_diags:
        status = "interval_invalid"
    if infeasible_idx:
        status = "device_infeasible"
        for k in infeasible_idx:
            detail = ("；".join(device_results[k]["diagnostics"])
                      if device_results[k]["diagnostics"] else "约束交集为空")
            joint_diags.append(
                f"设备 {k + 1}（区间 "
                f"[{device_results[k]['segment']['u0']:.2f}, "
                f"{device_results[k]['segment']['u1']:.2f}]m）无可行安装域：{detail}")

    # 逐机诊断前加区间前缀，便于面板按设备展示
    for k in infeasible_idx:
        prefix = f"[设备 {k + 1}｜覆盖区间 " \
                 f"[{device_results[k]['segment']['u0']:.2f}, " \
                 f"{device_results[k]['segment']['u1']:.2f}]m] "
        device_results[k]["diagnostics"] = [prefix + d for d in
                                            device_results[k]["diagnostics"]]

    # ---- 当前各点的联合校验（自身约束 + 检修包络两两相交）----
    point_conflicts = []
    for i in range(n):
        if points[i] is None or not device_results[i]["feasible"]:
            continue
        pt = device_results[i]["point"]
        if pt and not pt["ok"]:
            bad = [name for name, ok in pt["checks"].items() if not ok]
            names = {"throw": "投射距离", "shift": "水平位移", "wall": "墙面余量",
                     "obstacle": "检修净距/禁装区", "height": "镜头高度"}
            point_conflicts.append({
                "type": "self", "devices": [i],
                "message": f"设备 {i + 1} 当前点不满足：" +
                           "、".join(names.get(b, b) for b in bad) +
                           (f"（与禁装区「{pt['obstacle_hit']}」相交）"
                            if pt.get("obstacle_hit") else ""),
            })
    for i in range(n):
        for j in range(i + 1, n):
            if points[i] is None or points[j] is None:
                continue
            if not device_results[i]["feasible"] or \
                    not device_results[j]["feasible"]:
                continue
            ei = service_envelope(points[i]["x"], points[i]["y"],
                                  devs[i]["bw"], devs[i]["bd"],
                                  devs[i]["clearance"])
            ej = service_envelope(points[j]["x"], points[j]["y"],
                                  devs[j]["bw"], devs[j]["bd"],
                                  devs[j]["clearance"])
            if rects_intersect(ei, ej):
                point_conflicts.append({
                    "type": "pair", "devices": [i, j],
                    "envelopes": [_round_rect(ei), _round_rect(ej)],
                    "message": f"设备 {i + 1} 与设备 {j + 1} 的检修包络相交"
                               f"（净距 {devs[i]['clearance']:.2f}/"
                               f"{devs[j]['clearance']:.2f}m 未满足）",
                })

    # ---- 联合求解（逐机均可行且区间合法时）----
    if status == "ok":
        sol = _solve_joint(devs, wants=points)
        if sol["status"] != "ok":
            # 采样复核：逐对判定，找出相互无法兼容的设备对作为冲突来源
            pair_bad = []
            for i in range(n):
                for j in range(i + 1, n):
                    if not _grid_feasible_pair(devs[i], devs[j]):
                        pair_bad.append((i, j))
            if pair_bad:
                for i, j in pair_bad:
                    joint_diags.append(
                        f"联合约束冲突：设备 {i + 1}（区间 "
                        f"[{device_results[i]['segment']['u0']:.2f}, "
                        f"{device_results[i]['segment']['u1']:.2f}]m）与设备 "
                        f"{j + 1}（区间 "
                        f"[{device_results[j]['segment']['u0']:.2f}, "
                        f"{device_results[j]['segment']['u1']:.2f}]m）的可行域"
                        f"无法同时满足检修包络互避（净距 "
                        f"{devs[i]['clearance']:.2f}/{devs[j]['clearance']:.2f}m）")
            else:
                joint_diags.append(
                    "联合约束冲突：逐机均有可行域，但不存在一组安装点使全部"
                    "检修包络两两不相交（多台设备的可行域组合相互挤占）")
            status = "joint_infeasible"
        else:
            suggested = sol["points"]

    # ---- 用户当前点整体是否成立 ----
    points_given = any(p is not None for p in points)
    if status == "ok":
        if points_given:
            all_ok = (not point_conflicts and
                      all(device_results[k]["point"]
                          and device_results[k]["point"]["ok"] for k in range(n)))
            if not all_ok:
                status = "joint_conflict"
        # 未给当前点时，建议点即为可用解，整体视为成立（前端采纳建议点）
        joint_ok = status == "ok"
    else:
        joint_ok = False

    return {
        "status": status,
        "joint_ok": joint_ok,
        "feasible": status in ("ok", "joint_conflict"),
        "count": n,
        "screen": {"left": round(left, 4), "right": round(right, 4),
                   "width": round(Sw, 4)},
        "overlaps": [{"between": [k, k + 1], "value": round(ov, 4),
                      "required": round(need, 4), "ok": ov + EPS >= need}
                     for k, (ov, need) in enumerate(overlaps)],
        "devices": device_results,
        "suggested_points": ([{"x": round(p["x"], 4), "y": round(p["y"], 4)}
                              for p in suggested]
                             if suggested and all(p is not None for p in suggested)
                             else None),
        "point_conflicts": point_conflicts,
        "diagnostics": joint_diags,
    }
