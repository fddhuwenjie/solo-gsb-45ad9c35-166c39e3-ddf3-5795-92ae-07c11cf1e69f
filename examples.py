"""内置示例场景。所有尺寸单位：米；投射比无量纲；位移为幕宽/幕高的比例。

每个示例 data 中：
  room / screen / schemes / obstacles 为单机模式与拼接模式共用的基础参数；
  blend 为可选项，给出 2~3 台拼接时的覆盖区间（u0,u1 为幕布坐标，0=幕左沿、
  Sw=幕右沿，允许越界）、每台镜头参数引用、最小拼接重叠与机身检修净距。
"""

EXAMPLES = [
    {
        "id": "conf",
        "name": "示例 1：标准会议室 6.5×8m",
        "data": {
            "room": {"width": 6.5, "depth": 8.0, "height": 2.8, "margin": 0.3},
            "screen": {"width": 2.2, "height": 1.24, "bottom": 0.9, "cx": 3.25},
            "schemes": [
                {"name": "标准镜头 1.3–2.1", "tr_min": 1.3, "tr_max": 2.1,
                 "h_shift": 0.30, "v_shift": 0.50,
                 "body_w": 0.40, "body_d": 0.32, "body_h": 0.15},
                {"name": "短焦镜头 0.8–1.0", "tr_min": 0.8, "tr_max": 1.0,
                 "h_shift": 0.10, "v_shift": 0.20,
                 "body_w": 0.42, "body_d": 0.35, "body_h": 0.16},
                {"name": "长焦镜头 2.0–3.2", "tr_min": 2.0, "tr_max": 3.2,
                 "h_shift": 0.50, "v_shift": 0.60,
                 "body_w": 0.45, "body_d": 0.38, "body_h": 0.18},
                {"name": "定焦镜头 1.3–2.1（水平位移 0，安装线）",
                 "tr_min": 1.3, "tr_max": 2.1,
                 "h_shift": 0.0, "v_shift": 0.50,
                 "body_w": 0.40, "body_d": 0.32, "body_h": 0.15},
            ],
            "obstacles": [
                {"name": "吊灯", "x": 2.65, "y": 3.4, "w": 1.2, "h": 0.8},
                {"name": "横梁", "x": 0.0, "y": 5.2, "w": 6.5, "h": 0.4},
                {"name": "空调柜机", "x": 5.6, "y": 0.3, "w": 0.6, "h": 0.6},
            ],
        },
    },
    {
        "id": "training",
        "name": "示例 2：小型培训室 5×6m",
        "data": {
            "room": {"width": 5.0, "depth": 6.0, "height": 2.6, "margin": 0.25},
            "screen": {"width": 1.8, "height": 1.01, "bottom": 0.95, "cx": 2.5},
            "schemes": [
                {"name": "超短焦 0.4–0.5", "tr_min": 0.4, "tr_max": 0.5,
                 "h_shift": 0.05, "v_shift": 0.10,
                 "body_w": 0.38, "body_d": 0.30, "body_h": 0.12},
                {"name": "标准镜头 1.4–2.2", "tr_min": 1.4, "tr_max": 2.2,
                 "h_shift": 0.25, "v_shift": 0.45,
                 "body_w": 0.36, "body_d": 0.28, "body_h": 0.13},
                {"name": "长焦镜头 2.2–3.0", "tr_min": 2.2, "tr_max": 3.0,
                 "h_shift": 0.40, "v_shift": 0.55,
                 "body_w": 0.44, "body_d": 0.40, "body_h": 0.17},
            ],
            "obstacles": [
                {"name": "结构柱", "x": 3.6, "y": 2.2, "w": 0.5, "h": 0.5},
                {"name": "吊灯", "x": 1.9, "y": 3.6, "w": 1.0, "h": 0.7},
            ],
        },
    },
    {
        "id": "hall",
        "name": "示例 3：报告厅 10×14m（含无解方案）",
        "data": {
            "room": {"width": 10.0, "depth": 14.0, "height": 3.6, "margin": 0.4},
            "screen": {"width": 4.0, "height": 2.25, "bottom": 1.0, "cx": 5.0},
            "schemes": [
                {"name": "标准镜头 1.4–2.3", "tr_min": 1.4, "tr_max": 2.3,
                 "h_shift": 0.30, "v_shift": 0.55,
                 "body_w": 0.50, "body_d": 0.45, "body_h": 0.20},
                {"name": "长焦镜头 2.2–3.5", "tr_min": 2.2, "tr_max": 3.5,
                 "h_shift": 0.50, "v_shift": 0.65,
                 "body_w": 0.55, "body_d": 0.50, "body_h": 0.22},
                {"name": "超长焦 3.6–5.0", "tr_min": 3.6, "tr_max": 5.0,
                 "h_shift": 0.60, "v_shift": 0.70,
                 "body_w": 0.60, "body_d": 0.55, "body_h": 0.25},
            ],
            "obstacles": [
                {"name": "舞台灯光架", "x": 3.0, "y": 2.0, "w": 4.0, "h": 0.6},
                {"name": "楼座挑台", "x": 0.0, "y": 11.0, "w": 10.0, "h": 2.0},
                {"name": "设备间", "x": 8.6, "y": 6.0, "w": 1.4, "h": 2.0},
            ],
            # 两台拼接：各覆盖 2.2m 区间（互叠 0.2m，两端各越界 0.1m）
            "blend": {
                "segments": [
                    {"scheme_idx": 0, "u0": -0.1, "u1": 2.1,
                     "min_overlap": 0.20, "clearance": 0.30},
                    {"scheme_idx": 1, "u0": 1.9, "u1": 4.1,
                     "min_overlap": 0.20, "clearance": 0.30},
                ],
            },
        },
    },
    {
        "id": "blend2",
        "name": "示例 4：大会议室双机拼接 10×10m（6m 幕）",
        "data": {
            "room": {"width": 10.0, "depth": 10.0, "height": 3.6, "margin": 0.3},
            "screen": {"width": 6.0, "height": 3.0, "bottom": 1.0, "cx": 5.0},
            "schemes": [
                {"name": "拼接机标准镜头 1.3–2.0", "tr_min": 1.3, "tr_max": 2.0,
                 "h_shift": 0.60, "v_shift": 0.55,
                 "body_w": 0.42, "body_d": 0.35, "body_h": 0.16},
                {"name": "拼接机长焦 1.8–2.6", "tr_min": 1.8, "tr_max": 2.6,
                 "h_shift": 0.60, "v_shift": 0.55,
                 "body_w": 0.48, "body_d": 0.42, "body_h": 0.18},
            ],
            "obstacles": [
                {"name": "中置吊灯", "x": 4.3, "y": 4.6, "w": 1.4, "h": 0.9},
            ],
            # 两台各覆盖约 3.2m 区间，互叠 0.3m，两端各越界 0.1m
            "blend": {
                "segments": [
                    {"scheme_idx": 0, "u0": -0.1, "u1": 3.1,
                     "min_overlap": 0.30, "clearance": 0.25},
                    {"scheme_idx": 1, "u0": 2.8, "u1": 6.1,
                     "min_overlap": 0.30, "clearance": 0.30},
                ],
            },
            # 画面融合校准：目标 255±15 cd/m²；融合带 [2.8,3.1] 沿幕布
            # 坐标 5 个左右单侧亮度采样（边缘轻微滚降）
            "calibration": {
                "target": {"luminance": 255, "tolerance": 15},
                "devices": [
                    {"base_luminance": 300, "attenuation_min": 0.70,
                     "attenuation_max": 1.00},
                    {"base_luminance": 300, "attenuation_min": 0.70,
                     "attenuation_max": 1.00},
                ],
                "overlap_samples": [
                    [{"u": 2.85, "left": 299.4, "right": 286.1},
                     {"u": 2.90, "left": 297.8, "right": 291.1},
                     {"u": 2.95, "left": 295.0, "right": 295.0},
                     {"u": 3.00, "left": 291.1, "right": 297.8},
                     {"u": 3.05, "left": 286.1, "right": 299.4}],
                ],
            },
        },
    },
    {
        "id": "blend3",
        "name": "示例 5：报告厅三机拼接 14×14m（9m 弧幕等效）",
        "data": {
            "room": {"width": 14.0, "depth": 14.0, "height": 4.5, "margin": 0.4},
            "screen": {"width": 9.0, "height": 4.5, "bottom": 0.6, "cx": 7.0},
            "schemes": [
                {"name": "左/右机镜头 1.2–1.8", "tr_min": 1.2, "tr_max": 1.8,
                 "h_shift": 0.80, "v_shift": 0.60,
                 "body_w": 0.50, "body_d": 0.45, "body_h": 0.20},
                {"name": "中机镜头 1.2–1.8", "tr_min": 1.2, "tr_max": 1.8,
                 "h_shift": 0.40, "v_shift": 0.60,
                 "body_w": 0.50, "body_d": 0.45, "body_h": 0.20},
            ],
            "obstacles": [
                {"name": "灯控桥架", "x": 0.0, "y": 8.8, "w": 14.0, "h": 0.5},
            ],
            # 三台各覆盖约 3.35m 区间，邻接互叠 0.25m，两端各越界 0.1m
            "blend": {
                "segments": [
                    {"scheme_idx": 0, "u0": -0.1, "u1": 3.25,
                     "min_overlap": 0.25, "clearance": 0.35},
                    {"scheme_idx": 1, "u0": 3.0, "u1": 6.35,
                     "min_overlap": 0.25, "clearance": 0.35},
                    {"scheme_idx": 0, "u0": 6.1, "u1": 9.1,
                     "min_overlap": 0.25, "clearance": 0.35},
                ],
            },
            # 画面融合校准：中机以同一个衰减同时满足左右两个融合带
            "calibration": {
                "target": {"luminance": 255, "tolerance": 15},
                "devices": [
                    {"base_luminance": 300, "attenuation_min": 0.70,
                     "attenuation_max": 1.00},
                    {"base_luminance": 300, "attenuation_min": 0.70,
                     "attenuation_max": 1.00},
                    {"base_luminance": 300, "attenuation_min": 0.70,
                     "attenuation_max": 1.00},
                ],
                "overlap_samples": [
                    [{"u": 3.0417, "left": 299.4, "right": 286.1},
                     {"u": 3.0833, "left": 297.8, "right": 291.1},
                     {"u": 3.125, "left": 295.0, "right": 295.0},
                     {"u": 3.1667, "left": 291.1, "right": 297.8},
                     {"u": 3.2083, "left": 286.1, "right": 299.4}],
                    [{"u": 6.1417, "left": 299.4, "right": 286.1},
                     {"u": 6.1833, "left": 297.8, "right": 291.1},
                     {"u": 6.225, "left": 295.0, "right": 295.0},
                     {"u": 6.2667, "left": 291.1, "right": 297.8},
                     {"u": 6.3083, "left": 286.1, "right": 299.4}],
                ],
            },
        },
    },
]
