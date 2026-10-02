"""会议室投影机选位工作台 — Flask 后端。"""
from flask import Flask, jsonify, render_template, request

import calibration
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


@app.post("/api/calibrate")
def api_calibrate():
    """画面融合亮度校准（几何复用 /api/blend 结果）。

    入参与 /api/blend 相同（room/screen/segments/obstacles/points/
    lens_heights），另加：
      target:  {luminance, tolerance}，整幅幕布目标亮度与 ±容差（cd/m²）
      calibration: [{base_luminance, attenuation_min, attenuation_max}] × N
                   每台实测基准亮度与可调衰减（输出保留系数 0~1）上下限
      overlap_samples: [[{u,left,right}, …] × (N-1)]
                   每个相邻重叠带沿幕布坐标 u 的左右单侧亮度采样（≥2 点）
    仅在拼接几何成立（覆盖连续、逐机可行、联合安装点互避）时求解；否则
    原样返回 blend 诊断（calibration.status="blend_invalid"），不输出
    任何校准值。测量缺失/衰减无共同解时返回带设备或重叠定位的诊断。
    """
    data = request.get_json(force=True, silent=False)
    try:
        room = data["room"]
        screen = data["screen"]
        obstacles = data.get("obstacles", [])
        segments = data["segments"]
        if not (geometry.BLEND_MIN <= len(segments) <= geometry.BLEND_MAX):
            return jsonify({
                "error": f"覆盖区间数量必须为 {geometry.BLEND_MIN}~"
                         f"{geometry.BLEND_MAX} 个（当前 {len(segments)} 个）",
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

        blend = geometry.compute_blend(
            room, screen, segments, obstacles, points, lens_heights)

        target = data.get("target") or {}
        device_meas = data.get("calibration")
        overlap_samples = data.get("overlap_samples")
        if device_meas is None or overlap_samples is None or not target:
            return jsonify({"error":
                            "缺少 target / calibration / overlap_samples 参数"}), 400

        cal = calibration.compute_calibration(
            segments, device_meas, target, overlap_samples, screen["width"])
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"参数无效: {exc}"}), 400

    # 几何不成立：不输出任何校准值，仅回传 blend 结果与定位
    if blend["status"] not in ("ok", "joint_conflict"):
        cal = dict(cal)
        cal["status"] = "blend_invalid"
        cal["calibrated"] = False
        cal["attenuations"] = None
        cal["bands"] = None
        cal["predictions"] = None
        cal["blend_diagnostics"] = blend["diagnostics"]
    return jsonify({"blend": blend, "calibration": cal})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
