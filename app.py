"""会议室投影机选位工作台 — Flask 后端。"""
import math

from flask import Flask, jsonify, render_template, request

import geometry
from examples import EXAMPLES

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/examples")
def api_examples():
    return jsonify(EXAMPLES)


@app.post("/api/compute")
def api_compute():
    data = request.get_json(force=True, silent=False)
    try:
        room = data["room"]
        screen = data["screen"]
        schemes = data.get("schemes", [])
        obstacles = data.get("obstacles", [])
        point = data.get("point")
        lens_height = data.get("lens_height")
        results = [
            geometry.compute_scheme(room, screen, s, obstacles, point, lens_height)
            for s in schemes
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"参数无效: {exc}"}), 400
    return jsonify({"schemes": results})


@app.post("/api/blend")
def api_blend():
    """多机拼接规划联合求解。

    入参：
      room, screen, obstacles 同 /api/compute
      segments: [2~3] 个有序覆盖区间，每项
        {scheme: {..., u0, u1}, min_overlap, clearance}
        u0/u1 为覆盖区间端点（幕布坐标，0=幕左沿、幕宽=幕右沿，可越界）
      points:        可选，[{x,y}] × N，用户当前安装点
      lens_heights:  可选，[float] × N
    返回联合状态、每台安装域（单机结果 + 区间信息）、建议安装点与诊断。
    """
    data = request.get_json(force=True, silent=False)
    try:
        room = data["room"]
        screen = data["screen"]
        obstacles = data.get("obstacles", [])
        segments = data["segments"]
        if not (geometry.BLEND_MIN <= len(segments) <= geometry.BLEND_MAX):
            return jsonify({
                "error": f"覆盖区间数量必须为 {geometry.BLEND_MIN}~{geometry.BLEND_MAX} 个"
                         f"（当前 {len(segments)} 个）",
            }), 400
        for i, seg in enumerate(segments):
            scheme = seg["scheme"]
            float(scheme["u0"])
            float(scheme["u1"])
            float(seg.get("min_overlap", 0.0))
            float(seg.get("clearance", 0.0))
        points = data.get("points")
        lens_heights = data.get("lens_heights")
        if points is not None and len(points) != len(segments):
            return jsonify({"error": "points 数量必须与覆盖区间数量一致"}), 400
        if lens_heights is not None and len(lens_heights) != len(segments):
            return jsonify({"error": "lens_heights 数量必须与覆盖区间数量一致"}), 400
        result = geometry.compute_blend(
            room, screen, segments, obstacles, points, lens_heights)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"参数无效: {exc}"}), 400
    return jsonify(result)


def _finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


@app.post("/api/calibrate")
def api_calibrate():
    """画面融合校准联合求解（拼接输入沿用 /api/blend）。

    额外入参：
      target:  {"luminance": >0, "tolerance": >=0 且 < luminance}
      devices: [{"base_luminance": >0, "att_min", "att_max"}] × N
                （实测基准亮度与可调衰减上下限，0 ≤ att_min ≤ att_max ≤ 1）
      overlaps: [{"between": [k, k+1],
                  "samples": [{"u", "left", "right"}, …]}]
                每个实际存在的重叠带一条，采样沿幕布坐标给出两侧实测亮度
    返回确定性的逐机衰减值、各重叠端点权重与逐点预测亮度；测量缺失、
    衰减范围无共同解或原拼接无解时返回带设备/重叠定位的诊断。
    """
    data = request.get_json(force=True, silent=False)
    try:
        room = data["room"]
        screen = data["screen"]
        obstacles = data.get("obstacles", [])
        segments = data["segments"]
        n = len(segments)
        if not (geometry.BLEND_MIN <= n <= geometry.BLEND_MAX):
            return jsonify({
                "error": f"覆盖区间数量必须为 {geometry.BLEND_MIN}~{geometry.BLEND_MAX} 个"
                         f"（当前 {n} 个）",
            }), 400
        for seg in segments:
            scheme = seg["scheme"]
            float(scheme["u0"])
            float(scheme["u1"])
            float(seg.get("min_overlap", 0.0))
            float(seg.get("clearance", 0.0))
        points = data.get("points")
        lens_heights = data.get("lens_heights")
        if points is not None and len(points) != n:
            return jsonify({"error": "points 数量必须与覆盖区间数量一致"}), 400
        if lens_heights is not None and len(lens_heights) != n:
            return jsonify({"error": "lens_heights 数量必须与覆盖区间数量一致"}), 400

        target = data["target"]
        t_lum = float(target["luminance"])
        t_tol = float(target.get("tolerance", 0.0))
        if not (_finite(t_lum) and t_lum > 0):
            return jsonify({"error": "目标亮度必须为正数"}), 400
        if not (_finite(t_tol) and 0.0 <= t_tol < t_lum):
            return jsonify({"error": "亮度容差必须 ≥ 0 且小于目标亮度"}), 400

        devices = data["devices"]
        if len(devices) != n:
            return jsonify({"error": "devices 数量必须与覆盖区间数量一致"}), 400
        for i, d in enumerate(devices):
            base = float(d["base_luminance"])
            att_lo = float(d["att_min"])
            att_hi = float(d["att_max"])
            if not (_finite(base) and base > 0):
                return jsonify({"error": f"设备 {i + 1} 的实测基准亮度必须为正数"}), 400
            if not (_finite(att_lo) and _finite(att_hi)
                    and 0.0 <= att_lo <= att_hi <= 1.0):
                return jsonify({
                    "error": f"设备 {i + 1} 的可调衰减上下限需满足 "
                             f"0 ≤ 下限 ≤ 上限 ≤ 1（当前 {att_lo}~{att_hi}）",
                }), 400

        ub = [(float(s["scheme"]["u0"]), float(s["scheme"]["u1"]))
              for s in segments]
        overlaps_raw = data.get("overlaps", []) or []
        overlaps = []
        seen = set()
        for b in overlaps_raw:
            k, k2 = int(b["between"][0]), int(b["between"][1])
            if not (0 <= k < n - 1 and k2 == k + 1):
                return jsonify({
                    "error": "overlaps 的 between 必须为相邻设备编号 [k, k+1]",
                }), 400
            if k in seen:
                return jsonify({"error": f"重叠带 {k + 1} 的采样重复提交"}), 400
            seen.add(k)
            if ub[k][1] - ub[k + 1][0] <= geometry.EPS:
                # 几何上无重叠的相邻对：忽略其采样（区间问题由拼接层诊断）
                continue
            u0b, u1b = ub[k + 1][0], ub[k][1]
            samples = b.get("samples") or []
            if len(samples) > geometry.CAL_MAX_SAMPLES:
                return jsonify({
                    "error": f"每个重叠带的采样点数量不能超过 "
                             f"{geometry.CAL_MAX_SAMPLES} 个",
                }), 400
            for s in samples:
                u = float(s["u"])
                left = float(s["left"])
                right = float(s["right"])
                if not (_finite(u) and u0b - 1e-6 <= u <= u1b + 1e-6):
                    return jsonify({
                        "error": f"重叠带 {k + 1} 的采样点 u={s['u']} 不在带内 "
                                 f"[{u0b:.2f}, {u1b:.2f}]m",
                    }), 400
                if not (_finite(left) and _finite(right)
                        and left >= 0 and right >= 0):
                    return jsonify({
                        "error": f"重叠带 {k + 1} 的采样亮度必须为非负数值",
                    }), 400
            overlaps.append(b)

        cal = {
            "target": {"luminance": t_lum, "tolerance": t_tol},
            "devices": devices,
            "overlaps": overlaps,
        }
        result = geometry.compute_calibrate(
            room, screen, segments, obstacles, points, lens_heights, cal)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return jsonify({"error": f"参数无效: {exc}"}), 400
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
