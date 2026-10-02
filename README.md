# 会议室投影机选位工作台

基于 **Python Flask + 原生 JavaScript + SVG** 的 Web 工作台，支持两种工作模式：

- **单机选位**：给定房间、幕布、镜头参数与禁装区，计算并连续显示每个镜头方案的可安装区域；
- **多机拼接规划**：把同一幅幕布划成 2～3 个有序覆盖区间，逐台求可安装域，再给出一组同时满足全部拼接/检修约束的联合安装点；拼接成立后可继续做**画面融合校准**——为每台求全局一致的衰减值、为每个重叠带生成单调渐变权重，使整幅幕布的加权亮度落入目标容差。

## 一键启动

```bash
docker compose up --build
```

启动后用浏览器访问：

**http://localhost:8000**

停止：在终端按 `Ctrl+C`，或执行 `docker compose down`。

## 本地直接运行（可选，不使用 Docker）

```bash
pip install -r requirements.txt
python app.py
```

同样访问 http://localhost:8000 。

## 功能说明

### 单机选位（原有能力，接口保持兼容）

- **房间与幕布**：设置房间宽 / 进深 / 净高与墙面余量；设置幕布宽高、下沿离地高度，幕布可在顶视图直接拖动。
- **镜头方案**：录入投射比范围、水平/垂直镜头位移（±%）、机身宽深高；可添加多个方案。
- **禁装区**：点击「绘制禁装区」后在顶视图拖拽出矩形，可拖动移动、拖右下角缩放、Delete 键删除。
- **可安装区域计算**：投射距离带 ∩ 水平位移带 ∩ 墙面余量矩形，再扣除按机身尺寸膨胀的禁装区。
- **退化可行域（安装线）**：水平位移为 0 时退化为纵深安装线段，线段长度大于 0 即判可行（`domain="line"`）。
- **即时重算 / 无解诊断 / 双视图同步 / 选点校验 / 方案排序 / 内置示例**，详见下文计算模型。

### 多机拼接规划（新增）

在页头切换到「多机拼接」标签后：

1. **划分覆盖区间**：选择 2 或 3 台设备，系统默认均分整幅幕布（邻接重叠 0.2m、两端各越界 0.1m），可在「幕布条带」视图拖动各区间端点三角手柄，或在编辑卡直接填写 `u0/u1`（幕布坐标：0=幕左沿、幕宽=幕右沿，允许越出幕布边缘），「↔ 均分区间」可重分。
2. **每台镜头方案**：选择/编辑各台投射比、水平/垂直位移、机身尺寸，并填写
   - **最小拼接重叠**（米）：相邻两台覆盖区间的重叠不得小于双方要求的最大值；
   - **机身检修净距**（米）：机身矩形四周再外扩形成检修包络所需的净空。
3. **区间驱动的几何**：每个区间宽度**替代整幅幕宽**参与该台的投射比（`投射距离 = 投射比 × 区间宽`）与水平位移比例计算；**区间中心决定水平位移带**中心；垂直方向（幕高、下沿、垂直位移、净高）复用整幅幕布。
4. **联合求解**：系统复用现有墙面余量、垂直位移、禁装区扣除逻辑逐机求可安装域，再用精确矩形扣除 + DFS 搜索一组安装点，使
   - 覆盖区间从左到右**连续覆盖整幅幕布**（首尾覆盖幕左右沿、相邻无缝）；
   - 邻接重叠 **不小于要求**；
   - 各机**检修包络彼此之间、与禁装区之间均不得相交**（边界接触允许）。
5. **诊断**：任一设备无解、区间非法（留缝/重叠不足/区间无序/未到幕边）、或逐机可行但联合约束冲突时，面板明确指出**设备编号、覆盖区间与冲突来源**（具体禁装区名称、冲突设备对、约束类型），**不保存部分方案**。
6. **拖动即时重算**：顶视图/侧视图/幕布条带中拖动任一安装点、区间端点、幕布、禁装区均在 40ms 防抖后重算；初次解算自动采纳服务器建议点，拖动中若当前点冲突则保留用户点并以绿色 `×` 标出服务器建议点（可点击采纳，或按「⤷ 采纳服务器建议安装点」）。
7. **视图同步**：
   - **顶视图**：各机可安装域、区间覆盖光锥、幕布墙上的邻接重叠带（绿色斜纹=达标、红色=不足）、机身/检修包络虚线框（冲突时标红）、当前安装点与建议点；
   - **侧视图**：各机“投射距离×镜头高度”可行域与机身，镜头高度逐机独立可调；
   - **幕布条带**：每台一行覆盖条，斜纹高亮邻接重叠并标注实测重叠/要求，缝隙标红，端点三角可拖。
8. **内置示例**：示例 3（报告厅双机）、示例 4（双机 6m 幕）、示例 5（三机 9m 幕）携带拼接配置，载入后自动进入拼接模式。

### 画面融合校准（新增）

拼接联合成立（`status=ok`）后，「画面融合校准」卡片录入测量并实时求解：

1. **目标与容差**：整幅幕布的目标亮度与 ± 容差（同一目标区间适用于非重叠区与重叠带）。
2. **逐机测量**：每台录入**实测基准亮度**（未衰减时其非重叠区实测亮度）与**可调衰减上下限**（0～1）。
3. **重叠带采样**：为每个相邻重叠带录入沿幕布坐标的两侧亮度采样（`u` 为幕布坐标，`left/right` 为该点两台各自的实测亮度），可增删采样行。
4. **联合求解**：系统仅在**覆盖连续、各设备可行且联合安装成立**（沿用 `/api/blend` 结果）时计算——
   - 为每台选择一个**全局一致**的衰减值：非重叠区亮度 `基准 × 衰减` 落入容差；同一台参与两侧重叠时，一个衰减值同时满足两侧；
   - 为每个重叠带生成**从左机到右机的单调线性渐变权重**（带左端 左1/右0 → 带右端 左0/右1），使带内每个采样点的加权叠加亮度落入容差；
   - 约束是关于衰减值的线性不等式组，按重叠带分解为二维凸多边形精确求解（有界多面体非空 ⟺ 存在可行顶点）；解不唯一时取确定性规则——优先所有设备相同的**最小衰减** `g0=max(各窗口下限)`，不可行时取离 `(g0,…,g0)` 最近的可行点，输出完全确定。
5. **诊断（不输出部分校准）**：测量缺失（定位到重叠带）、衰减范围无共同解（定位到设备/重叠带/超差采样）、原拼接无解（沿用拼接诊断）时整体返回诊断；`no_common_attenuation` 附 `preview` 供页面标出超差采样，仅为诊断参考而非可应用的校准方案。
6. **幕布条带视图**：校准成立时融合带以左机→右机渐变填充并标注各机衰减值，采样点绿/红标记达标/超差，底部绘制**逐点预测亮度曲线**（绿色带为目标容差区间）；测量缺失的融合带标注「缺采样」。

## HTTP 接口

### `GET /api/examples`

返回内置示例（单机 + 拼接）。

### `POST /api/compute` — 单机计算（保持不变）

```bash
curl -X POST http://localhost:8000/api/compute \
  -H 'Content-Type: application/json' \
  -d '{
    "room": {"width": 6.5, "depth": 8.0, "height": 2.8, "margin": 0.3},
    "screen": {"width": 2.2, "height": 1.24, "bottom": 0.9, "cx": 3.25},
    "schemes": [{
      "name": "标准镜头 1.3–2.1",
      "tr_min": 1.3, "tr_max": 2.1, "h_shift": 0.30, "v_shift": 0.50,
      "body_w": 0.40, "body_d": 0.32, "body_h": 0.15
    }],
    "obstacles": [],
    "point": {"x": 3.25, "y": 3.6},
    "lens_height": 1.55
  }'
```

返回 `{"schemes": [ {feasible, domain, region, base_rect, ranges, point, diagnostics, …} ]}`。

### `POST /api/blend` — 多机拼接规划（新增）

`segments` 为 2～3 个从左到右的有序覆盖区间；每个区间的 `scheme` 在单机镜头参数外增加 `u0/u1`（覆盖区间端点，幕布坐标，可越界），并携带该台要求的 `min_overlap`（最小拼接重叠）与 `clearance`（机身检修净距）。`points` / `lens_heights` 可选，给出时逐台做当前点校验；`suggested_points` 为服务器联合求解给出的一组可行安装点。

```bash
curl -X POST http://localhost:8000/api/blend \
  -H 'Content-Type: application/json' \
  -d '{
    "room": {"width": 10.0, "depth": 10.0, "height": 3.6, "margin": 0.3},
    "screen": {"width": 6.0, "height": 3.0, "bottom": 1.0, "cx": 5.0},
    "obstacles": [{"name": "中置吊灯", "x": 4.3, "y": 4.6, "w": 1.4, "h": 0.9}],
    "segments": [
      {
        "scheme": {"name": "1号机", "tr_min": 1.3, "tr_max": 2.0,
                   "h_shift": 0.6, "v_shift": 0.55,
                   "body_w": 0.42, "body_d": 0.35, "body_h": 0.16,
                   "u0": -0.1, "u1": 3.1},
        "min_overlap": 0.30, "clearance": 0.25
      },
      {
        "scheme": {"name": "2号机", "tr_min": 1.8, "tr_max": 2.6,
                   "h_shift": 0.6, "v_shift": 0.55,
                   "body_w": 0.48, "body_d": 0.42, "body_h": 0.18,
                   "u0": 2.8, "u1": 6.1},
        "min_overlap": 0.30, "clearance": 0.30
      }
    ]
  }'
```

返回（节选）：

```json
{
  "status": "ok",
  "joint_ok": true,
  "feasible": true,
  "count": 2,
  "overlaps": [{"between": [0, 1], "value": 0.3, "required": 0.3, "ok": true}],
  "devices": [
    {"name": "1号机", "feasible": true, "domain": "area", "area": 6.5,
     "region": [[…]], "base_rect": […], "ranges": {…},
     "segment": {"u0": -0.1, "u1": 3.1, "width": 3.2, "center": 1.5,
                 "min_overlap": 0.3, "clearance": 0.25,
                 "overlap_right": 0.3, "overlap_required": 0.3},
     "point": null, "diagnostics": []}
  ],
  "suggested_points": [{"x": 2.71, "y": 5.28}, {"x": 6.45, "y": 7.26}],
  "point_conflicts": [],
  "diagnostics": []
}
```

`status` 取值：

| status | 含义 |
| --- | --- |
| `ok` | 区间合法、逐机可行、联合解存在；给了当前点且全部成立时 `joint_ok=true` |
| `joint_conflict` | 联合解存在（`suggested_points` 非空），但用户当前点不满足自身约束或检修包络相交，明细见 `point_conflicts` |
| `interval_invalid` | 覆盖区间非法：未从左到右有序、未连续覆盖整幅幕布（留缝/未到幕边）或邻接重叠不足 |
| `device_infeasible` | 至少一台无可安装域，逐机诊断带 `[设备 k｜覆盖区间 [u0,u1]m]` 前缀并点名冲突约束/禁装区 |
| `joint_infeasible` | 各机单独可行但不存在一组安装点使检修包络两两互避，诊断给出冲突设备对 |

拖动场景下把当前点作为 `points` 回传即可得到 `joint_conflict` + 实时 `suggested_points`；采纳后再次回传即回到 `ok`。区间数量不为 2～3 或参数缺失时返回 HTTP 400 与 `error` 说明。

### `POST /api/calibrate` — 画面融合校准（新增）

拼接输入（`room` / `screen` / `obstacles` / `segments` / `points` / `lens_heights`）与 `/api/blend` 完全相同，另需：

- `target`: `{"luminance": >0, "tolerance": ≥0 且 < luminance}` — 整幅幕布目标亮度与容差；
- `devices`: `[{"base_luminance": >0, "att_min", "att_max"}] × N` — 每台实测基准亮度与可调衰减上下限（`0 ≤ att_min ≤ att_max ≤ 1`）；
- `overlaps`: `[{"between": [k, k+1], "samples": [{"u", "left", "right"}, …]}]` — 每个实际存在的相邻重叠带一条；`u` 为幕布坐标（须在带内），`left/right` 为该点两台的实测亮度；每带最多 64 个采样点。无几何重叠的相邻对提交的采样被忽略。

```bash
curl -X POST http://localhost:8000/api/calibrate \
  -H 'Content-Type: application/json' \
  -d '{
    "room": {"width": 10.0, "depth": 10.0, "height": 3.6, "margin": 0.3},
    "screen": {"width": 6.0, "height": 3.0, "bottom": 1.0, "cx": 5.0},
    "obstacles": [{"name": "中置吊灯", "x": 4.3, "y": 4.6, "w": 1.4, "h": 0.9}],
    "segments": [
      {"scheme": {"name": "1号机", "tr_min": 1.3, "tr_max": 2.0,
                  "h_shift": 0.6, "v_shift": 0.55,
                  "body_w": 0.42, "body_d": 0.35, "body_h": 0.16,
                  "u0": -0.1, "u1": 3.1},
       "min_overlap": 0.30, "clearance": 0.25},
      {"scheme": {"name": "2号机", "tr_min": 1.8, "tr_max": 2.6,
                  "h_shift": 0.6, "v_shift": 0.55,
                  "body_w": 0.48, "body_d": 0.42, "body_h": 0.18,
                  "u0": 2.8, "u1": 6.1},
       "min_overlap": 0.30, "clearance": 0.30}
    ],
    "target": {"luminance": 150.0, "tolerance": 12.0},
    "devices": [
      {"base_luminance": 165.0, "att_min": 0.60, "att_max": 1.0},
      {"base_luminance": 158.0, "att_min": 0.60, "att_max": 1.0}
    ],
    "overlaps": [
      {"between": [0, 1], "samples": [
        {"u": 2.85, "left": 165.0, "right": 157.0},
        {"u": 2.95, "left": 164.0, "right": 158.0},
        {"u": 3.05, "left": 163.0, "right": 159.0}
      ]}
    ]
  }'
```

返回（节选）：

```json
{
  "status": "ok",
  "calibrated": true,
  "count": 2,
  "blend_status": "ok",
  "target": {"luminance": 150.0, "tolerance": 12.0},
  "attenuations": [
    {"device": 0, "value": 0.8734, "range": [0.6, 1.0], "base_luminance": 165.0,
     "window": [0.8364, 0.9818], "non_overlap_luminance": 144.1139, "ok": true},
    {"device": 1, "value": 0.8734, "range": [0.6, 1.0], "base_luminance": 158.0,
     "window": [0.8734, 1.0], "non_overlap_luminance": 138.0, "ok": true}
  ],
  "overlaps": [
    {"between": [0, 1], "u0": 2.8, "u1": 3.1,
     "weights": {"u0": {"left": 1.0, "right": 0.0}, "u1": {"left": 0.0, "right": 1.0}},
     "samples": [
       {"u": 2.95, "t": 0.5, "w_left": 0.5, "w_right": 0.5,
        "measured_left": 164.0, "measured_right": 158.0,
        "left": 71.6203, "right": 69.0, "total": 140.6203, "deviation": -9.3797, "ok": true}
     ]}
  ],
  "screen_samples": [
    {"u": 0.0, "luminance": 144.1139, "device": 0, "overlap": null, "ok": true},
    {"u": 2.95, "luminance": 140.6203, "device": null, "overlap": 0,
     "w_left": 0.5, "w_right": 0.5, "ok": true}
  ],
  "diagnostics": []
}
```

`status` 取值（失败时 `calibrated=false`，不输出 `attenuations`/`overlaps`/`screen_samples`）：

| status | 含义 |
| --- | --- |
| `ok` | 校准成立：返回确定性的逐机衰减值、各重叠端点权重与逐点预测亮度 |
| `measurement_missing` | 存在未录入采样的重叠带，`missing` 列出其设备对与幕布坐标区间 |
| `no_common_attenuation` | 衰减范围无共同解：诊断点名冲突设备、重叠带或中间设备两侧矛盾；`preview` 为诊断参考（参考衰减下的逐点预测，用于标出超差采样），非可应用方案 |
| `blend_interval_invalid` / `blend_device_infeasible` / `blend_joint_infeasible` / `blend_joint_conflict` | 原拼接未成立（区间非法 / 设备无解 / 联合冲突 / 当前点冲突），诊断沿用 `/api/blend` 结果，校准未执行 |

参数缺失或非法（目标亮度非正、容差为负或不小于目标、衰减上下限越界、采样点越出重叠带、重叠带重复提交等）返回 HTTP 400 与 `error` 说明。

## 文件结构

```
app.py              # Flask 服务：/api/compute（单机）、/api/blend（拼接）、/api/calibrate（校准）、/api/examples
geometry.py         # 约束交集、矩形扣除、诊断、选点校验、多机联合求解与画面融合校准核心
examples.py         # 内置示例场景（单机 + 拼接 blend 配置 + 校准 calibrate 测量）
test_calibrate.py   # 校准自检脚本（python3 test_calibrate.py，不依赖 Flask）
templates/index.html
static/app.js       # 单机/拼接双模式状态管理、三视图 SVG 渲染、校准编辑与拖拽交互
static/style.css
Dockerfile / docker-compose.yml
```

## 计算模型

顶视图坐标：原点为前墙左角，x 向右、y 由幕布墙指向后墙（米）。镜头位于机身前表面中央，单机机身占位矩形为 `[px-bw/2, px+bw/2] × [py, py+bd]`。单机可安装区域：

```
[投射距离带] ∩ [水平位移带] ∩ [墙面余量矩形] \ ⋃(禁装区按机身尺寸膨胀)
```

退化情形：x 交集宽度为 0 而 y 区间长度大于 0 时为固定 x 的安装线（`domain="line"`，`line_length` 给出扣除禁装区后的可行总长度）。

多机拼接时，第 k 台以“覆盖区间 [u0,u1] 构成的虚拟幕布”参与同一套单机求解：

```
区间宽 Wk = u1-u0  →  投射距离带 py ∈ [tr_min·Wk, tr_max·Wk]
区间中心 Ck        →  水平位移带 px ∈ [Ck-hs, Ck+hs]，hs = h_shift·Wk
垂直位移、墙面余量、禁装区扣除规则与单机一致（禁装区再四周外扩 clearance）
```

检修包络 = 机身矩形四周外扩 `clearance`。设备 a、b 的包络互不相交，等价于 b 的镜头点不得落在”a 的包络按 b 的半机身宽/机深/净距再膨胀”的矩形内——联合求解据此把已定位设备逐一作为矩形禁区从待定位设备可行域（二维矩形集或安装线段）中精确扣除，DFS 找到每台都能定位的一组点即成功；失败时逐对做栅格复核以点名冲突设备对。全程使用与单机一致的开区间接触规则（仅边界接触不判碰撞）。

画面融合校准在拼接联合成立后叠加一层线性约束求解：

```
非重叠区：  base_k · att_k ∈ [T−tol, T+tol]     → 逐机衰减窗口 win_k
重叠带 k：  m_l·att_k·(1−t) + m_r·att_{k+1}·t ∈ [T−tol, T+tol]
            （t 为采样点在带内的归一化位置，权重 (1−t, t) 从左机到右机单调渐变）
```

全部约束为衰减值的线性不等式，可行域有界（衰减有上下限）。每个重叠带的约束只涉及相邻两台，构成二维凸多边形；有界多面体非空 ⟺ 存在可行顶点（顶点必为两条约束边界线交点），枚举精确判定。三机两带时，联合可行 ⟺ 两个多边形在中间设备衰减轴上的投影区间相交——同一台的衰减值由此同时满足两侧重叠。解不唯一时取确定性规则：优先全局一致的最小衰减 `g0 = max(各窗口下限)`，不可行时取离 `(g0,…,g0)` 最近的可行点；无随机、无迭代初值，同一输入必然得到同一输出。

`/api/compute`、`/api/examples` 的字段与既有行为完全兼容，单机示例与 Docker Compose 启动方式不变。
