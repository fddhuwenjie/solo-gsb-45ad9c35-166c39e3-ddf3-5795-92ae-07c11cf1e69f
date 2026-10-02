"""画面融合校准（geometry.compute_calibrate）与 /api/calibrate 路由的自检脚本。

不依赖 Flask：路由测试通过 stub flask 模块完成。直接运行：
    python3 test_calibrate.py
全部断言通过时输出 OK 并退出码 0。
"""
import copy
import json
import sys
import types

import geometry
from examples import EXAMPLES


def blend_example(ex_id):
    """把示例的 blend 配置展开为 /api/blend 风格的请求体。"""
    ex = next(e for e in EXAMPLES if e["id"] == ex_id)
    d = copy.deepcopy(ex["data"])
    segments = []
    for seg in d["blend"]["segments"]:
        scheme = dict(d["schemes"][seg["scheme_idx"]])
        scheme["u0"] = seg["u0"]
        scheme["u1"] = seg["u1"]
        segments.append({"scheme": scheme,
                         "min_overlap": seg["min_overlap"],
                         "clearance": seg["clearance"]})
    cal = d["blend"]["calibrate"]
    return {
        "room": d["room"], "screen": d["screen"], "obstacles": d["obstacles"],
        "segments": segments,
        "target": {"luminance": cal["target"], "tolerance": cal["tolerance"]},
        "devices": cal["devices"],
        "overlaps": cal["overlaps"],
    }


def run_cal(payload):
    p = copy.deepcopy(payload)
    cal = {"target": p.pop("target"), "devices": p.pop("devices"),
           "overlaps": p.pop("overlaps")}
    return geometry.compute_calibrate(
        p["room"], p["screen"], p["segments"], p["obstacles"],
        p.get("points"), p.get("lens_heights"), cal)


def check(name, cond, extra=""):
    assert cond, f"FAIL: {name} {extra}"
    print(f"  ok: {name}")


# ---------------------------------------------------------------- 示例正向
print("== 内置示例校准均应为 ok ==")
for ex_id in ("hall", "blend2", "blend3"):
    payload = blend_example(ex_id)
    res = run_cal(payload)
    check(f"{ex_id} status ok", res["status"] == "ok", res.get("diagnostics"))
    check(f"{ex_id} calibrated", res["calibrated"] is True)
    n = res["count"]
    check(f"{ex_id} 衰减数量", len(res["attenuations"]) == n)
    for a in res["attenuations"]:
        check(f"{ex_id} 衰减在可调范围内",
              a["range"][0] - 1e-9 <= a["value"] <= a["range"][1] + 1e-9)
        check(f"{ex_id} 非重叠区亮度在容差内",
              abs(a["non_overlap_luminance"] - res["target"]["luminance"])
              <= res["target"]["tolerance"] + 1e-6)
    for band in res["overlaps"]:
        check(f"{ex_id} 端点权重",
              band["weights"]["u0"] == {"left": 1.0, "right": 0.0} and
              band["weights"]["u1"] == {"left": 0.0, "right": 1.0})
        for s in band["samples"]:
            check(f"{ex_id} 采样 u={s['u']} 在容差内", s["ok"],
                  f"total={s['total']}")
            check(f"{ex_id} 权重单调", 0 <= s["w_right"] <= 1 and
                  abs(s["w_left"] + s["w_right"] - 1.0) < 1e-9)
    check(f"{ex_id} 逐点预测全部达标",
          all(p["ok"] for p in res["screen_samples"]))
    # 确定性：同一输入两次求解结果完全一致
    res2 = run_cal(payload)
    check(f"{ex_id} 确定性", json.dumps(res, sort_keys=True) ==
          json.dumps(res2, sort_keys=True))

# ---------------------------------------------------------------- 测量缺失
print("== 测量缺失 ==")
payload = blend_example("blend2")
payload["overlaps"] = []
res = run_cal(payload)
check("缺采样 → measurement_missing", res["status"] == "measurement_missing")
check("不输出校准", res["calibrated"] is False and "attenuations" not in res)
check("定位到重叠带", res["missing"][0]["between"] == [0, 1] and
      abs(res["missing"][0]["u0"] - 2.8) < 1e-9)

payload = blend_example("blend3")
payload["overlaps"] = payload["overlaps"][:1]     # 只给第 1 条带
res = run_cal(payload)
check("三机缺一条带 → measurement_missing",
      res["status"] == "measurement_missing")
check("缺失定位为带 2", res["missing"][0]["between"] == [1, 2])

# ---------------------------------------------------------------- 衰减无共同解：窗口
print("== 衰减窗口无交集 ==")
payload = blend_example("blend2")
payload["devices"][0]["base_luminance"] = 300.0
payload["devices"][0]["att_min"] = 0.9     # 设备1即使大力衰减仍过亮
payload["devices"][1]["base_luminance"] = 120.0
payload["devices"][1]["att_min"] = 0.95    # 设备2不衰减仍偏暗
res = run_cal(payload)
check("窗口无交集 → no_common_attenuation",
      res["status"] == "no_common_attenuation")
check("不输出校准", res["calibrated"] is False and "attenuations" not in res)
check("诊断点名设备", any("设备 1" in d for d in res["diagnostics"]) and
      any("设备 2" in d for d in res["diagnostics"]))
check("给出各机衰减窗口", len(res["windows"]) == 2)
check("诊断预览存在", "preview" in res and
      len(res["preview"]["overlaps"][0]["samples"]) == 3)

# ---------------------------------------------------------------- 衰减无共同解：重叠带
print("== 重叠带采样不可满足 ==")
payload = blend_example("blend2")
# 带内右侧实测亮度异常高：任何衰减下叠加都超上限
payload["overlaps"][0]["samples"][1]["right"] = 400.0
res = run_cal(payload)
check("带不可行 → no_common_attenuation",
      res["status"] == "no_common_attenuation")
check("诊断定位重叠带 1", any("重叠带 1" in d for d in res["diagnostics"]))
bad = [s for s in res["preview"]["overlaps"][0]["samples"] if not s["ok"]]
check("预览标出超差采样", len(bad) >= 1)

# ---------------------------------------------------------------- 三机：中间设备两侧冲突
print("== 三机中间设备两侧冲突 ==")
payload = blend_example("blend3")
# 左带：中机实测偏亮 → att_2 需 ≤ 0.85；右带：中机实测偏暗 → att_2 需 ≥ 0.92；
# 两条带各自可行，但同一台设备的衰减无法同时满足两侧
for s in payload["overlaps"][0]["samples"]:
    s["right"] = 201.0
for s in payload["overlaps"][1]["samples"]:
    s["left"] = 140.0
res = run_cal(payload)
check("两侧冲突 → no_common_attenuation",
      res["status"] == "no_common_attenuation")
check("诊断点名设备 2 两侧重叠", any("设备 2" in d and "两侧" in d
                                     for d in res["diagnostics"]))

# ---------------------------------------------------------------- 原拼接无解
print("== 原拼接未成立 ==")
payload = blend_example("blend2")
payload["segments"][1]["scheme"]["u0"] = 3.5   # 与左机之间留缝
res = run_cal(payload)
check("区间留缝 → blend_interval_invalid",
      res["status"] == "blend_interval_invalid")
check("不输出校准", res["calibrated"] is False and "attenuations" not in res)
check("沿用拼接诊断", any("缝" in d for d in res["diagnostics"]))

payload = blend_example("blend2")
payload["segments"][0]["scheme"]["tr_min"] = 9.0  # 左机投射距离超房间进深
payload["segments"][0]["scheme"]["tr_max"] = 9.5
res = run_cal(payload)
check("设备无解 → blend_device_infeasible",
      res["status"] == "blend_device_infeasible")

# ---------------------------------------------------------------- 权重单调性
print("== 渐变权重单调 ==")
payload = blend_example("blend3")
res = run_cal(payload)
for band in res["overlaps"]:
    ws = [s["w_left"] for s in band["samples"]]
    check("左机权重沿 u 单调不增",
          all(ws[i] >= ws[i + 1] - 1e-9 for i in range(len(ws) - 1)))

# ---------------------------------------------------------------- 非一致衰减解
print("== 非一致衰减解（g0 不可行时取最近可行点）==")
payload = blend_example("blend2")
# t=0.5 采样处 g0=(0.8734,0.8734) 越上限，但 att_1 调低后整体可行
payload["overlaps"][0]["samples"] = [
    {"u": 2.85, "left": 165.0, "right": 200.0},
    {"u": 2.95, "left": 165.0, "right": 210.0},
    {"u": 3.05, "left": 165.0, "right": 170.0},
]
res = run_cal(payload)
check("非一致解存在", res["status"] == "ok")
vals = [a["value"] for a in res["attenuations"]]
check("设备 1 衰减低于 g0", vals[0] < 0.8734 - 1e-4, str(vals))
check("全部采样达标", all(s["ok"] for b in res["overlaps"] for s in b["samples"]))

# ---------------------------------------------------------------- 无重叠带
print("== 区间相接无重叠带 ==")
payload = blend_example("blend2")
payload["segments"][0]["scheme"]["u1"] = 3.0
payload["segments"][1]["scheme"]["u0"] = 3.0
payload["segments"][0]["min_overlap"] = 0.0
payload["segments"][1]["min_overlap"] = 0.0
payload["overlaps"] = []
res = run_cal(payload)
check("无重叠带仍校准", res["status"] == "ok" and res["overlaps"] == [])

# ---------------------------------------------------------------- 采样乱序
print("== 采样乱序确定性 ==")
payload = blend_example("blend2")
r1 = run_cal(payload)
payload["overlaps"][0]["samples"] = list(reversed(payload["overlaps"][0]["samples"]))
r2 = run_cal(payload)
check("乱序结果一致", json.dumps(r1, sort_keys=True) ==
      json.dumps(r2, sort_keys=True))

# ---------------------------------------------------------------- 退化多边形
print("== 退化可行多边形（点/线段）==")
poly = geometry._poly_from_constraints(
    [(1, 0, 0.5), (-1, 0, -0.5), (0, 1, 0.7), (0, -1, -0.7)])
check("单点可行域", len(poly) == 1)
check("单点最近点不越界", geometry._poly_closest(poly, 0.1, 0.1) == poly[0])
poly = geometry._poly_from_constraints(
    [(1, 0, 0.5), (-1, 0, -0.5), (0, 1, 1.0), (0, -1, 0.0)])
check("线段可行域", len(poly) == 2)
c = geometry._poly_closest(poly, 0.5, 5.0)
check("线段最近点夹到端点", abs(c[0] - 0.5) < 1e-9 and abs(c[1] - 1.0) < 1e-9)
c = geometry._poly_closest(poly, 0.5, 0.4)
check("线段内部取自身", abs(c[0] - 0.5) < 1e-9 and abs(c[1] - 0.4) < 1e-9)

# 固定衰减（上下限相同）端到端
payload = blend_example("blend2")
for dev in payload["devices"]:
    dev["att_min"] = dev["att_max"] = 0.88
res = run_cal(payload)
check("固定衰减求解", res["status"] == "ok" and
      all(abs(a["value"] - 0.88) < 1e-9 for a in res["attenuations"]))

# ---------------------------------------------------------------- 路由级（stub flask）
print("== /api/calibrate 路由 ==")
flask_stub = types.ModuleType("flask")


class _Resp:
    def __init__(self, data):
        self._data = data

    def get_json(self):
        return self._data


def _jsonify(obj):
    return _Resp(obj)


class _Flask:
    def __init__(self, name):
        self.routes = {}

    def get(self, path):
        def deco(fn):
            self.routes[("GET", path)] = fn
            return fn
        return deco

    def post(self, path):
        def deco(fn):
            self.routes[("POST", path)] = fn
            return fn
        return deco

    def run(self, **kw):
        pass


class _Request:
    payload = None

    @classmethod
    def get_json(cls, force=True, silent=False):
        return cls.payload


flask_stub.Flask = _Flask
flask_stub.jsonify = _jsonify
flask_stub.request = _Request
flask_stub.render_template = lambda name, **kw: ""
sys.modules["flask"] = flask_stub

import app as app_module  # noqa: E402

route = app_module.app.routes[("POST", "/api/calibrate")]


def call(payload):
    _Request.payload = payload
    out = route()
    if isinstance(out, tuple):
        return out[1], out[0].get_json()
    return 200, out.get_json()


code, body = call(blend_example("blend2"))
check("路由 200 + ok", code == 200 and body["status"] == "ok")

p = blend_example("blend2")
p["devices"] = p["devices"][:1]
code, body = call(p)
check("devices 数量不符 → 400", code == 400 and "error" in body)

p = blend_example("blend2")
p["devices"][0]["att_min"] = 0.9
p["devices"][0]["att_max"] = 0.4
code, body = call(p)
check("衰减上下限颠倒 → 400", code == 400)

p = blend_example("blend2")
p["target"]["tolerance"] = -5
code, body = call(p)
check("负容差 → 400", code == 400)

p = blend_example("blend2")
p["overlaps"][0]["samples"][0]["u"] = 1.0     # 采样点不在带内
code, body = call(p)
check("采样点越出重叠带 → 400", code == 400)

p = blend_example("blend2")
p["overlaps"].append(p["overlaps"][0])        # 重复提交同一重叠带
code, body = call(p)
check("重叠带重复 → 400", code == 400)

p = blend_example("blend2")
p["segments"] = p["segments"][:1]
code, body = call(p)
check("区间数量非法 → 400", code == 400)

# 单机/拼接既有接口保持可用
code, body = (200, None)
_Request.payload = {
    "room": {"width": 6.5, "depth": 8.0, "height": 2.8, "margin": 0.3},
    "screen": {"width": 2.2, "height": 1.24, "bottom": 0.9, "cx": 3.25},
    "schemes": [{"name": "s", "tr_min": 1.3, "tr_max": 2.1, "h_shift": 0.3,
                 "v_shift": 0.5, "body_w": 0.4, "body_d": 0.32,
                 "body_h": 0.15}],
}
out = app_module.app.routes[("POST", "/api/compute")]()
check("/api/compute 仍可用", "schemes" in out.get_json())
_Request.payload = blend_example("blend2")
out = app_module.app.routes[("POST", "/api/blend")]()
check("/api/blend 仍可用", out.get_json()["status"] == "ok")

print("\nOK: 全部自检通过")
