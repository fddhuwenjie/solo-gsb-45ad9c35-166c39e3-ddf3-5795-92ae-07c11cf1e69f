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

import math

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


# ==========================================================================
# 画面融合校准
#
# 在 /api/blend 联合求解成立（覆盖连续、逐机可行、联合安装成立）后，
# 为每台投影机选择一个全局一致的衰减值 att_k ∈ [att_min_k, att_max_k]：
#   非重叠区：亮度 = base_k · att_k 须落入 [T−tol, T+tol]
#     → 每台得衰减窗口 win_k = [att_min, att_max] ∩ [(T−tol)/base, (T+tol)/base]
#   重叠带 k（设备 k 与 k+1 之间 [u0,u1]）：权重从带左端 (左1, 右0) 到带右端
#     (左0, 右1) 单调线性渐变，采样点 u 处 t=(u−u0)/(u1−u0)，叠加亮度
#       B(u) = m_l·att_k·(1−t) + m_r·att_{k+1}·t  同样须落入 [T−tol, T+tol]
# 同一台设备参与两侧重叠时，其衰减值同时出现在两个重叠带的约束中。
#
# 全部约束都是关于衰减值的线性不等式，可行域是有界凸多面体（衰减有上下界）。
# n≤3 时按重叠带分解为若干二维问题精确求解：每个重叠带的约束只涉及
# (att_k, att_{k+1})，可行集为二维凸多边形；有界多面体非空 ⟺ 存在可行顶点，
# 顶点必为某两条约束边界线的交点，枚举即可。三机两带时，联合可行 ⟺ 两个
# 多边形在中间设备衰减轴上的投影相交（投影均为区间）。
#
# 解不唯一时取确定性规则：优先采用“全局一致的最小衰减”
# g0 = max(各窗口下限)（所有设备取同一值、画面尽量亮）；g0 不可行时取
# 离 (g0,…,g0) 最近的可行点。全程无随机、无迭代初值，输出确定。
# ==========================================================================

CAL_MAX_SAMPLES = 64        # 每个重叠带允许的最大采样点数
_CAL_VERT_EPS = 1e-7        # 顶点可行性判定的数值余量


def _att_window(base, att_lo, att_hi, target, tol):
    """单机衰减窗口：att ∈ [att_lo,att_hi] 且 base·att ∈ [T−tol,T+tol]。"""
    return (max(att_lo, (target - tol) / base),
            min(att_hi, (target + tol) / base))


def _poly_from_constraints(cons):
    """二维线性不等式组 a·x+b·y ≤ c 的可行凸多边形顶点（绕质心角序）。

    调用方保证变量有上下界（可行域有界）。有界多面体非空 ⟺ 存在可行顶点，
    顶点必为两条非平行边界线的交点；无可行顶点即空可行域，返回 []。
    """
    verts = []
    m = len(cons)
    for i in range(m):
        a1, b1, c1 = cons[i]
        for j in range(i + 1, m):
            a2, b2, c2 = cons[j]
            det = a1 * b2 - a2 * b1
            if abs(det) <= 1e-12:
                continue
            x = (c1 * b2 - c2 * b1) / det
            y = (a1 * c2 - a2 * c1) / det
            if all(a * x + b * y <= c + _CAL_VERT_EPS for a, b, c in cons):
                if not any(abs(x - ux) <= 1e-9 and abs(y - uy) <= 1e-9
                           for ux, uy in verts):
                    verts.append((x, y))
    if not verts:
        return []
    cx = sum(p[0] for p in verts) / len(verts)
    cy = sum(p[1] for p in verts) / len(verts)
    verts.sort(key=lambda p: (math.atan2(p[1] - cy, p[0] - cx),
                              (p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    return verts


def _poly_range(poly, axis):
    """多边形顶点在指定坐标轴（0=x, 1=y）上的投影区间。"""
    vals = [p[axis] for p in poly]
    return (min(vals), max(vals))


def _poly_section(poly, axis, v):
    """多边形与直线 axis=v 的交集在另一轴上的区间；为空返回 None。"""
    out = []
    m = len(poly)
    for i in range(m):
        p, q = poly[i], poly[(i + 1) % m]
        dp, dq = p[axis] - v, q[axis] - v
        if abs(dp) <= 1e-12 and abs(dq) <= 1e-12:
            out.extend((p[1 - axis], q[1 - axis]))
        elif dp * dq <= 0 and abs(q[axis] - p[axis]) > 1e-12:
            t = (v - p[axis]) / (q[axis] - p[axis])
            out.append(p[1 - axis] + t * (q[1 - axis] - p[1 - axis]))
    if not out:
        return None
    return (min(out), max(out))


def _seg_closest(x1, y1, x2, y2, px, py):
    """线段上离 (px,py) 最近的点。"""
    dx, dy = x2 - x1, y2 - y1
    ll = dx * dx + dy * dy
    if ll <= 1e-24:
        return (x1, y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / ll))
    return (x1 + t * dx, y1 + t * dy)


def _poly_closest(poly, gx, gy):
    """凸多边形（顶点角序）内离 (gx,gy) 最近的点；等距时取先扫描到者。"""
    m = len(poly)
    if m <= 2:
        # 退化为点或线段：角序内外判定不适用，直接取线段最近点
        best, best_d = None, None
        for i in range(m):
            p, q = poly[i], poly[(i + 1) % m]
            c = _seg_closest(p[0], p[1], q[0], q[1], gx, gy)
            d = (c[0] - gx) ** 2 + (c[1] - gy) ** 2
            if best is None or d < best_d - 1e-18:
                best, best_d = c, d
        return best
    if all((q[0] - p[0]) * (gy - p[1]) - (q[1] - p[1]) * (gx - p[0]) >= -1e-12
           for p, q in ((poly[i], poly[(i + 1) % m]) for i in range(m))):
        return (gx, gy)
    best, best_d = None, None
    for i in range(m):
        p, q = poly[i], poly[(i + 1) % m]
        c = _seg_closest(p[0], p[1], q[0], q[1], gx, gy)
        d = (c[0] - gx) ** 2 + (c[1] - gy) ** 2
        if best is None or d < best_d - 1e-18:
            best, best_d = c, d
    return best


def _band_constraints(band, win_k, win_k1, target, tol):
    """重叠带关于 (att_k, att_{k+1}) 的线性约束（含两台各自的衰减窗口）。"""
    cons = [(1.0, 0.0, win_k[1]), (-1.0, 0.0, -win_k[0]),
            (0.0, 1.0, win_k1[1]), (0.0, -1.0, -win_k1[0])]
    for s in band["samples"]:
        cl = s["left"] * (1.0 - s["t"])
        cr = s["right"] * s["t"]
        cons.append((cl, cr, target + tol))
        cons.append((-cl, -cr, -(target - tol)))
    return cons


def _solve_attenuations(devs_cal, bands, target, tol):
    """联合衰减求解。

    devs_cal: [{"base", "att_lo", "att_hi", "win": (lo, hi)}] × N
    bands:    [{"k", "u0", "u1", "samples": [{"u","t","left","right"}]}]
              k 为重叠带左侧设备编号
    返回 (atts 或 None, detail)；atts 为每台一个全局一致的衰减值。
    """
    n = len(devs_cal)
    g0 = max(d["win"][0] for d in devs_cal)      # 全局一致的最小衰减
    g1 = min(d["win"][1] for d in devs_cal)
    if g0 > g1 + EPS:
        return None, {"case": "windows"}

    polys = {}
    for band in bands:
        k = band["k"]
        cons = _band_constraints(band, devs_cal[k]["win"], devs_cal[k + 1]["win"],
                                 target, tol)
        polys[k] = _poly_from_constraints(cons)
        if not polys[k]:
            return None, {"case": "band", "band": k}

    if not bands:
        return [g0] * n, {"case": "ok"}

    if n == 2:
        x, y = _poly_closest(polys[0], g0, g0)
        return [x, y], {"case": "ok"}

    # n == 3：带 0 约束 (att_1, att_2)，带 1 约束 (att_2, att_3)
    atts = [g0, g0, g0]
    if 0 in polys and 1 in polys:
        ya = _poly_range(polys[0], 1)       # att_2 在左侧重叠带的可行区间
        xa = _poly_range(polys[1], 0)       # att_2 在右侧重叠带的可行区间
        lo, hi = max(ya[0], xa[0]), min(ya[1], xa[1])
        if lo > hi + EPS:
            return None, {"case": "shared", "left": ya, "right": xa}
        a2 = min(max(g0, lo), hi)
        sec_l = _poly_section(polys[0], 1, a2)      # att_1 的可行区间
        sec_r = _poly_section(polys[1], 0, a2)      # att_3 的可行区间
        atts = [min(max(g0, sec_l[0]), sec_l[1]), a2,
                min(max(g0, sec_r[0]), sec_r[1])]
    elif 0 in polys:
        x, y = _poly_closest(polys[0], g0, g0)
        atts = [x, y, min(max(g0, devs_cal[2]["win"][0]), devs_cal[2]["win"][1])]
    else:
        x, y = _poly_closest(polys[1], g0, g0)
        atts = [min(max(g0, devs_cal[0]["win"][0]), devs_cal[0]["win"][1]), x, y]
    return atts, {"case": "ok"}


def _sample_reach(s, win_k, win_k1):
    """采样点在各自衰减窗口内可达的叠加亮度区间（双线性，极值在角点）。"""
    vals = [s["left"] * (1.0 - s["t"]) * ak + s["right"] * s["t"] * ak1
            for ak in win_k for ak1 in win_k1]
    return (min(vals), max(vals))


def _cal_failure_diags(detail, devs_cal, bands, target, tol):
    """衰减无解时按设备/重叠带定位的诊断。"""
    diags = []
    if detail["case"] == "windows":
        for k, d in enumerate(devs_cal):
            empty = d["win"][0] > d["win"][1] + EPS
            diags.append(
                f"设备 {k + 1}：基准亮度 {d['base']:.1f}，可调衰减 "
                f"[{d['att_lo']:.2f}, {d['att_hi']:.2f}]，满足非重叠区目标 "
                f"{target:.1f}±{tol:.1f} 的衰减窗口为 "
                f"[{d['win'][0]:.4f}, {d['win'][1]:.4f}]" +
                ("（空窗口：即使" +
                 ("完全衰减仍过亮" if d["win"][1] < d["att_lo"] else "不衰减仍过暗") +
                 "）" if empty else ""))
        kmax = max(range(len(devs_cal)), key=lambda k: devs_cal[k]["win"][0])
        kmin = min(range(len(devs_cal)), key=lambda k: devs_cal[k]["win"][1])
        if kmax == kmin:
            diags.append(
                f"衰减范围无共同解：设备 {kmax + 1} 的衰减窗口本身为空（需同时 ≥ "
                f"{devs_cal[kmax]['win'][0]:.4f} 且 ≤ {devs_cal[kmax]['win'][1]:.4f}）"
                f"——请放宽该机的可调衰减上下限、复测基准亮度，或调整目标亮度/容差")
        else:
            diags.append(
                f"衰减范围无共同解：设备 {kmax + 1} 的衰减需 ≥ "
                f"{devs_cal[kmax]['win'][0]:.4f}，而设备 {kmin + 1} 的衰减需 ≤ "
                f"{devs_cal[kmin]['win'][1]:.4f}，公共区间为空——请放宽可调衰减"
                f"上下限、复测基准亮度，或调整目标亮度/容差")
    elif detail["case"] == "band":
        k = detail["band"]
        band = next(b for b in bands if b["k"] == k)
        diags.append(
            f"重叠带 {k + 1}（设备 {k + 1}↔{k + 2}，幕布坐标 "
            f"[{band['u0']:.2f}, {band['u1']:.2f}]m）：不存在同时满足该带全部"
            f"采样的衰减组合")
        impossible = []
        for s in band["samples"]:
            lo_s, hi_s = _sample_reach(s, devs_cal[k]["win"], devs_cal[k + 1]["win"])
            if lo_s > target + tol + _CAL_VERT_EPS or \
                    hi_s < target - tol - _CAL_VERT_EPS:
                impossible.append((s, lo_s, hi_s))
        for s, lo_s, hi_s in impossible[:4]:
            diags.append(
                f"　采样 u={s['u']:.2f}m：实测左 {s['left']:.1f} / 右 "
                f"{s['right']:.1f}，在两侧衰减窗口内可达亮度 "
                f"[{lo_s:.1f}, {hi_s:.1f}]，与目标区间 "
                f"[{target - tol:.1f}, {target + tol:.1f}] 无交集")
        if not impossible:
            diags.append(
                "　各采样单独均可达目标区间，但采样间相互冲突：同一对衰减值"
                "无法同时满足该带全部采样，请复核采样或加大容差")
    else:  # shared：中间设备的两侧投影不相交
        ya, yb = detail["left"], detail["right"]
        diags.append(
            f"设备 2 同时参与左右两侧重叠：左侧重叠带（设备 1↔2）要求其衰减 ∈ "
            f"[{ya[0]:.4f}, {ya[1]:.4f}]，右侧重叠带（设备 2↔3）要求 ∈ "
            f"[{yb[0]:.4f}, {yb[1]:.4f}]，两区间无交集——同一台设备的衰减值"
            f"无法同时满足两侧重叠带，请复测采样或调整衰减范围/容差")
    return diags


def _eval_band_samples(band, atts, target, tol):
    """按给定衰减逐采样点计算加权亮度（输出用，数值保留 4 位小数）。"""
    k = band["k"]
    rows = []
    for s in band["samples"]:
        t = s["t"]
        wl, wr = 1.0 - t, t
        lb = s["left"] * atts[k] * wl
        rb = s["right"] * atts[k + 1] * wr
        tot = lb + rb
        rows.append({
            "u": round(s["u"], 4), "t": round(t, 4),
            "w_left": round(wl, 4), "w_right": round(wr, 4),
            "measured_left": round(s["left"], 4),
            "measured_right": round(s["right"], 4),
            "left": round(lb, 4), "right": round(rb, 4),
            "total": round(tot, 4),
            "deviation": round(tot - target, 4),
            "ok": abs(tot - target) <= tol + 1e-6,
        })
    return rows


def compute_calibrate(room, screen, segments, obstacles, points, lens_heights,
                      cal):
    """画面融合校准联合求解（以 /api/blend 联合成立为前提）。

    cal = {
      "target":  {"luminance": >0, "tolerance": >=0},
      "devices": [{"base_luminance": >0, "att_min", "att_max"}] × N,
      "overlaps": [{"between": [k, k+1],
                    "samples": [{"u", "left", "right"}, …]}],
    }
    仅在覆盖连续、各设备可行且联合安装成立（blend status == "ok"）时计算；
    测量缺失、衰减无共同解或原拼接无解时整体返回带设备/重叠定位的诊断，
    不输出部分校准（失败时 preview 仅为诊断参考，不是可应用的校准方案）。
    """
    n = len(segments)
    target = float(cal["target"]["luminance"])
    tol = float(cal["target"].get("tolerance", 0.0))
    devices = cal["devices"]

    # ---- 原拼接联合求解（沿用 /api/blend 的结果与诊断）----
    blend = compute_blend(room, screen, segments, obstacles, points, lens_heights)
    resp = {
        "count": n,
        "blend_status": blend["status"],
        "target": {"luminance": round(target, 4), "tolerance": round(tol, 4)},
    }
    if blend["status"] != "ok":
        status_map = {
            "interval_invalid": "blend_interval_invalid",
            "device_infeasible": "blend_device_infeasible",
            "joint_infeasible": "blend_joint_infeasible",
            "joint_conflict": "blend_joint_conflict",
        }
        diags = ["原拼接规划未成立，画面融合校准未执行（先解决拼接问题）"]
        diags.extend(blend["diagnostics"])
        diags.extend(c["message"] for c in blend.get("point_conflicts", []))
        resp.update({
            "status": status_map.get(blend["status"], "blend_" + blend["status"]),
            "calibrated": False,
            "diagnostics": diags,
        })
        return resp

    # ---- 重叠带几何（由覆盖区间推导，与 /api/blend 的重叠口径一致）----
    ub = [(float(s["scheme"]["u0"]), float(s["scheme"]["u1"])) for s in segments]
    band_geo = {}
    for k in range(n - 1):
        if ub[k][1] - ub[k + 1][0] > EPS:
            band_geo[k] = (ub[k + 1][0], ub[k][1])

    # ---- 测量完整性：每个实际存在的重叠带都必须有两侧亮度采样 ----
    band_in = {}
    for b in cal.get("overlaps", []):
        band_in[int(b["between"][0])] = b
    diags = []
    missing = []
    bands = []
    for k in sorted(band_geo):
        u0, u1 = band_geo[k]
        b = band_in.get(k)
        samples = (b or {}).get("samples") or []
        if not samples:
            missing.append({"type": "overlap", "between": [k, k + 1],
                            "u0": round(u0, 4), "u1": round(u1, 4)})
            diags.append(
                f"重叠带 {k + 1}（设备 {k + 1}↔{k + 2}，幕布坐标 "
                f"[{u0:.2f}, {u1:.2f}]m）缺少沿幕布坐标的两侧亮度采样")
            continue
        ss = sorted(((float(s["u"]), float(s["left"]), float(s["right"]))
                     for s in samples), key=lambda r: r[0])
        bands.append({
            "k": k, "u0": u0, "u1": u1,
            "samples": [{"u": u,
                         "t": min(1.0, max(0.0, (u - u0) / (u1 - u0))),
                         "left": l, "right": r} for u, l, r in ss],
        })
    if diags:
        resp.update({"status": "measurement_missing", "calibrated": False,
                     "missing": missing, "diagnostics": diags})
        return resp

    # ---- 逐机衰减窗口 ----
    devs_cal = []
    for d in devices:
        base = float(d["base_luminance"])
        att_lo, att_hi = float(d["att_min"]), float(d["att_max"])
        devs_cal.append({"base": base, "att_lo": att_lo, "att_hi": att_hi,
                         "win": _att_window(base, att_lo, att_hi, target, tol)})
    windows_info = [{
        "device": k,
        "base_luminance": round(d["base"], 4),
        "range": [round(d["att_lo"], 4), round(d["att_hi"], 4)],
        "window": [round(d["win"][0], 4), round(d["win"][1], 4)],
    } for k, d in enumerate(devs_cal)]

    # ---- 联合衰减求解 ----
    atts, detail = _solve_attenuations(devs_cal, bands, target, tol)
    if atts is None:
        # 诊断参考：全局一致最小衰减（越界设备夹到自身边界）下的逐点预测
        g0 = max(d["win"][0] for d in devs_cal)
        ref = [min(max(g0, d["att_lo"]), d["att_hi"]) for d in devs_cal]
        preview = {
            "attenuations": [round(a, 4) for a in ref],
            "levels": [{"device": k,
                        "luminance": round(devs_cal[k]["base"] * ref[k], 4),
                        "ok": abs(devs_cal[k]["base"] * ref[k] - target)
                              <= tol + 1e-6}
                       for k in range(n)],
            "overlaps": [{
                "between": [band["k"], band["k"] + 1],
                "u0": round(band["u0"], 4), "u1": round(band["u1"], 4),
                "samples": _eval_band_samples(band, ref, target, tol),
            } for band in bands],
        }
        resp.update({
            "status": "no_common_attenuation", "calibrated": False,
            "windows": windows_info, "preview": preview,
            "diagnostics": _cal_failure_diags(detail, devs_cal, bands,
                                              target, tol),
        })
        return resp

    # ---- 成功：确定性输出（衰减值、重叠端点权重、逐点预测亮度）----
    att_out = [{
        "device": k,
        "value": round(atts[k], 4),
        "range": [round(devs_cal[k]["att_lo"], 4),
                  round(devs_cal[k]["att_hi"], 4)],
        "base_luminance": round(devs_cal[k]["base"], 4),
        "window": [round(devs_cal[k]["win"][0], 4),
                   round(devs_cal[k]["win"][1], 4)],
        "non_overlap_luminance": round(devs_cal[k]["base"] * atts[k], 4),
        "ok": True,
    } for k in range(n)]

    out_bands = [{
        "between": [band["k"], band["k"] + 1],
        "u0": round(band["u0"], 4), "u1": round(band["u1"], 4),
        "weights": {"u0": {"left": 1.0, "right": 0.0},
                    "u1": {"left": 0.0, "right": 1.0}},
        "samples": _eval_band_samples(band, atts, target, tol),
    } for band in bands]

    # 逐点预测亮度：非重叠区取该台衰减后基准亮度（每区左/中/右三点），
    # 重叠带内取各实测采样点的加权叠加值
    screen_pts = []
    sw = screen["width"]
    for k in range(n):
        lo_ex = ub[k][0] if k == 0 else max(ub[k][0], ub[k - 1][1])
        hi_ex = ub[k][1] if k == n - 1 else min(ub[k][1], ub[k + 1][0])
        a, b = max(lo_ex, 0.0), min(hi_ex, sw)
        if b - a > EPS:
            level = devs_cal[k]["base"] * atts[k]
            for u in (a, (a + b) / 2.0, b):
                screen_pts.append({
                    "u": round(u, 4), "luminance": round(level, 4),
                    "device": k, "overlap": None,
                    "ok": abs(level - target) <= tol + 1e-6,
                })
    for band, out in zip(bands, out_bands):
        for row in out["samples"]:
            screen_pts.append({
                "u": row["u"], "luminance": row["total"],
                "device": None, "overlap": band["k"],
                "w_left": row["w_left"], "w_right": row["w_right"],
                "ok": row["ok"],
            })
    screen_pts.sort(key=lambda p: (p["u"], p["overlap"] is None))

    resp.update({
        "status": "ok",
        "calibrated": True,
        "attenuations": att_out,
        "overlaps": out_bands,
        "screen_samples": screen_pts,
        "diagnostics": [],
    })
    return resp