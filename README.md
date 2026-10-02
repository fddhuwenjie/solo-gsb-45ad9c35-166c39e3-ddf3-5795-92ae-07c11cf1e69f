# 会议室投影机选位工作台

基于 **Python Flask + 原生 JavaScript + SVG** 的 Web 工作台，支持三种工作模式：

- **单机选位**：给定房间、幕布、镜头参数与禁装区，计算并连续显示每个镜头方案的可安装区域；
- **多机拼接规划**：把同一幅幕布划成 2～3 个有序覆盖区间，逐台求可安装域，再给出一组同时满足全部拼接/检修约束的联合安装点；
- **画面融合校准**：拼接几何成立后，为每台求**全局一致衰减值**、为每个重叠带求**从左机到右机的单调渐变权重**，使非重叠区与融合带的加权预测亮度全部落在目标容差内。

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

在「多机拼接」标签勾选「**启用画面融合校准**」后，在几何拼接之外录入实测亮度数据：

1. **目标亮度**：整幅幕布的目标亮度 `T` 与 ±容差 `δ`（cd/m²），容许区间为 `[T-δ, T+δ]`。
2. **每台测量**（在该设备编辑卡内）：实测**基准亮度**与**可调衰减上下限**。衰减为输出保留系数（0~1），`1.0`=不衰减、越小衰减越多；同一台参与左右两个融合带时**只取一个衰减值**，两侧同时满足。
3. **每个重叠带采样**：在「重叠带两侧亮度采样」卡沿幕布坐标 `u` 录入 ≥2 个严格递增点，每点给出**左机/右机单侧实测亮度**（单独点亮测得，cd/m²）。「✦ 生成/重置默认采样」按当前融合带几何与基准亮度生成 5 个可编辑初始点。
4. **求解模型**：系统仅在**覆盖连续、逐机可行、联合安装成立**时计算。设第 k 台衰减为 `g_k`：
   - 非重叠区亮度 `L = B_k·g_k`；
   - 融合带 `[a,b]` 内（左机 k、右机 k+1）采用从左机到右机**端点固定 (1,0)→(0,1) 的单调非增渐变权重** `w(u)`，
     `L(u) = w(u)·B_L(u)·g_k + (1-w(u))·B_R(u)·g_{k+1}`（单侧实测按幕布坐标分段线性插值）；
   - 以各 `g_k` 与公共裕量 `s` 为变量构成线性规划（最大化最小容差裕量，**内置两阶段单纯形，无第三方依赖**），再与“固定衰减、对每点命中目标的理想权重做保序回归”交替迭代，从线性/凸/凹/S 形多组确定性初始 ramp 中取裕量最大者，结果**确定性**。
5. **输出**：每台**衰减值**、各重叠带**端点与逐采样点权重**、非重叠区与融合带的**逐点预测亮度**。
6. **诊断（不输出部分校准）**：测量缺失/非法（采样不足、坐标越界或倒置、亮度为负、衰减范围无效）→ `measurement_invalid`；衰减范围与采样在目标容差内**无共同解**（中间设备无法以单一衰减同时满足两侧等）→ `no_common_solution`，按“移除后恢复可行”归因到**具体设备**（可达亮度区间与目标无交集）或**具体重叠带的超差采样点**（条带中红色 ✕/方框）；原拼接几何不成立 → `blend_invalid`，原样返回拼接诊断。
7. **幕布条带**：底部新增「融合预测亮度」行——绿色斜纹标出融合带、绿色横带为目标容差区、蓝色折线为逐点预测亮度、超差点位以红色 ✕ 标出。
8. **内置示例**：示例 4（双机）、示例 5（三机）同时携带 `calibration` 配置，载入即自动启用并完成校准。

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

### `POST /api/calibrate` — 画面融合亮度校准（新增）

请求体**包含 `/api/blend` 的全部字段**（`room/screen/segments/obstacles/points/lens_heights`，沿用 `/api/blend` 的几何结果），另加：

| 字段 | 说明 |
| --- | --- |
| `target` | `{luminance, tolerance}`：整幅幕布目标亮度与 ±容差（cd/m²） |
| `calibration` | 每台一项 `{base_luminance, attenuation_min, attenuation_max}`：实测基准亮度与衰减（输出保留系数 0~1）上下限 |
| `overlap_samples` | 每个相邻重叠带一个数组，每项 `{u,left,right}`：沿幕布坐标 `u` 的左右单侧亮度采样（≥2 个、严格递增、落在该融合带内） |

```bash
curl -X POST http://localhost:8000/api/calibrate \
  -H 'Content-Type: application/json' \
  -d '{
    "room": {"width": 10.0, "depth": 10.0, "height": 3.6, "margin": 0.3},
    "screen": {"width": 6.0, "height": 3.0, "bottom": 1.0, "cx": 5.0},
    "obstacles": [{"name": "中置吊灯", "x": 4.3, "y": 4.6, "w": 1.4, "h": 0.9}],
    "segments": [
      {"scheme": {"name": "1号机", "tr_min": 1.3, "tr_max": 2.0, "h_shift": 0.6,
                  "v_shift": 0.55, "body_w": 0.42, "body_d": 0.35, "body_h": 0.16,
                  "u0": -0.1, "u1": 3.1},
       "min_overlap": 0.30, "clearance": 0.25},
      {"scheme": {"name": "2号机", "tr_min": 1.8, "tr_max": 2.6, "h_shift": 0.6,
                  "v_shift": 0.55, "body_w": 0.48, "body_d": 0.42, "body_h": 0.18,
                  "u0": 2.8, "u1": 6.1},
       "min_overlap": 0.30, "clearance": 0.30}
    ],
    "target": {"luminance": 255, "tolerance": 15},
    "calibration": [
      {"base_luminance": 300, "attenuation_min": 0.70, "attenuation_max": 1.00},
      {"base_luminance": 300, "attenuation_min": 0.70, "attenuation_max": 1.00}
    ],
    "overlap_samples": [
      [{"u": 2.85, "left": 299.4, "right": 286.1},
       {"u": 2.90, "left": 297.8, "right": 291.1},
       {"u": 2.95, "left": 295.0, "right": 295.0},
       {"u": 3.00, "left": 291.1, "right": 297.8},
       {"u": 3.05, "left": 286.1, "right": 299.4}]
    ]
  }'
```

返回 `{"blend": {…与 /api/blend 相同…}, "calibration": {…}}`。几何不成立时 `calibration.status="blend_invalid"` 且**不含任何衰减/权重/预测值**，并附 `blend_diagnostics`。几何成立时校准节选（成功）：

```json
{
  "status": "ok",
  "calibrated": true,
  "target": {"luminance": 255, "tolerance": 15, "lower": 240, "upper": 270},
  "attenuations": [
    {"index": 0, "attenuation": 0.8571, "output_luminance": 257.14},
    {"index": 1, "attenuation": 0.8571, "output_luminance": 257.14}
  ],
  "bands": [{
    "between": [0, 1], "u0": 2.8, "u1": 3.1, "width": 0.3, "skipped": false,
    "weights": [
      {"u": 2.8,  "w_left": 1.0,   "w_right": 0.0,   "endpoint": "left"},
      {"u": 2.85, "w_left": 0.87,  "w_right": 0.13},
      {"u": 3.1,  "w_left": 0.0,   "w_right": 1.0,   "endpoint": "right"}
    ]
  }],
  "predictions": {
    "points": [
      {"u": 1.4,  "luminance": 257.14, "within_tolerance": true, "region": "solo", "between": [0, 0]},
      {"u": 2.8,  "luminance": 257.14, "within_tolerance": true, "region": "overlap",
       "between": [0, 1], "w_left": 1.0, "w_right": 0.0, "endpoint": "left"},
      {"u": 2.95, "luminance": 252.86, "within_tolerance": true, "region": "overlap",
       "between": [0, 1], "w_left": 0.5, "w_right": 0.5, "measured": 295.0}
    ],
    "out_of_tolerance": []
  },
  "margin": 12.8571,
  "diagnostics": []
}
```

`calibration.status` 取值：

| status | 含义 |
| --- | --- |
| `ok` | 衰减与单调渐变权重全部确定，非重叠区与融合带逐点预测亮度都在 `[T-δ,T+δ]` 内，`margin` 为距最近容差边界的最小裕量（cd/m²） |
| `measurement_invalid` | 测量缺失/非法（设备亮度/衰减缺失、采样不足 2 点、坐标越界或非递增、亮度为负、衰减下限>上限等），`diagnostics` 带设备或重叠带定位，不输出校准 |
| `no_common_solution` | 衰减范围与采样在目标容差内无共同解（含中间设备单一衰减无法同时满足两侧）；`diagnostics` 点名设备（可达亮度区间）或具体重叠带超差采样点，`attenuations/bands` 为 `null`，`predictions` 用就近兜底衰减标注超差点位但**不构成校准结果** |
| `blend_invalid` | 原拼接几何不成立（`blend.status` 非 `ok/joint_conflict`），原样回传拼接诊断，不输出校准 |

端点权重恒为左端 `(w_left,w_right)=(1,0)`、右端 `(0,1)`，内部采样点权重从左到右单调非增；两区间仅端点相接（融合带宽 0）时该带 `skipped=true` 且无需采样。

## 文件结构

```
app.py              # Flask 服务：/api/compute（单机）、/api/blend（拼接）、/api/calibrate（融合校准）、/api/examples
geometry.py         # 约束交集、矩形扣除、诊断、选点校验与多机联合求解核心
calibration.py      # 融合亮度校准：两阶段单纯形 LP、保序回归单调权重、联合搜索与归因诊断
examples.py         # 内置示例场景（单机 + 拼接 blend + 校准 calibration 配置）
templates/index.html
static/app.js       # 单机/拼接/融合校准三模式状态管理、三视图 SVG 渲染、拖拽交互
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

检修包络 = 机身矩形四周外扩 `clearance`。设备 a、b 的包络互不相交，等价于 b 的镜头点不得落在“a 的包络按 b 的半机身宽/机深/净距再膨胀”的矩形内——联合求解据此把已定位设备逐一作为矩形禁区从待定位设备可行域（二维矩形集或安装线段）中精确扣除，DFS 找到每台都能定位的一组点即成功；失败时逐对做栅格复核以点名冲突设备对。全程使用与单机一致的开区间接触规则（仅边界接触不判碰撞）。

画面融合校准在几何拼接成立（`/api/blend` 的 `status ∈ {ok, joint_conflict}`）后进行。以各台衰减 `g_k`（同一台参与两侧融合带时为同一变量）与公共归一化裕量 `s` 为变量，非重叠区约束 `1-δ+s ≤ (B_k/T)g_k ≤ 1+δ-s`，融合带采样点约束 `1-δ+s ≤ w(B_L/T)g_k + (1-w)(B_R/T)g_{k+1} ≤ 1+δ-s`，边界 `gmin_k ≤ g_k ≤ gmax_k`、`s ≥ 0`，构成线性规划并最大化 `s`（内置 Bland 准则两阶段单纯形，结果确定、零第三方依赖）。权重 `w` 在各采样点为自由的单调变量：固定权重时衰减是上述 LP；固定衰减时每点“恰好命中 T 的理想权重”再做端点固定 (1,0)→(0,1) 的单调非增**保序回归（PAVA）**；二者交替迭代，并从线性/凸/凹/S 形四组确定性初始 ramp 出发取裕量最大者。无解时按约束分组做“移除后恢复可行”复核，定位到设备的可达亮度区间或具体重叠带的超差采样点，且不输出任何校准值。

`/api/compute`、`/api/blend`、`/api/examples` 的字段与既有行为完全兼容，单机/拼接示例与 Docker Compose 启动方式不变；新增能力仅通过 `/api/calibrate` 与拼接模式下的“画面融合校准”开关提供。
