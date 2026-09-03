# -*- coding: utf-8 -*-
"""商品图选品工具：上传商品图，AI 视觉识别品类/特征后自动跑选品分析。

设计要点：
1. 视觉识别：用 DashScope Qwen-VL 多模态大模型分析商品图，提取品类、材质、风格等
2. 自动选品：识别出的品类直接喂给智能选品分析，零人工干预
3. 降级策略：视觉 API 不可用时，提示用户手动输入品类

流程：上传商品图 → Qwen-VL 识别品类+特征 → 智能选品分析 → 合并报告
"""
import os
import base64
import time
from pathlib import Path
from typing import Dict, Any, Optional

from langchain_core.tools import tool

from config import LOG_DIR
from 模块.日志统计 import get_file_logger
logger = get_file_logger("商品图选品")

# DashScope API Key（复用视频/图片生成的 key）
_DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# 上传图片目录
UPLOAD_DIR = Path(__file__).parent.parent / "静态资源" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _encode_image_to_base64(image_path: str) -> str:
    """将本地图片编码为 base64 data URL。"""
    full_path = _resolve_image_path(image_path)
    if not full_path or not full_path.exists():
        return ""
    with open(full_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _resolve_image_path(image_path: str) -> Optional[Path]:
    """解析图片路径（本地路径或 /uploads/* 路径）。"""
    if image_path.startswith("/uploads/"):
        p = UPLOAD_DIR / image_path.replace("/uploads/", "")
        if p.exists():
            return p
    p = Path(image_path)
    if p.exists():
        return p
    # 尝试在 uploads 目录下按文件名匹配
    filename = Path(image_path).name
    search = UPLOAD_DIR / filename
    if search.exists():
        return search
    return None


def analyze_product_image(image_path: str, requirements: str = "") -> Dict[str, Any]:
    """调用 Qwen-VL 分析商品图，提取品类、特征、风格等信息。

    Args:
        image_path: 图片路径（/uploads/xxx.jpg 或本地绝对路径）
        requirements: 用户附加的选品要求（如目标市场、预算等）

    Returns:
        {
            "品类": str, "商品名": str, "材质": str, "风格": str,
            "卖点": [str], "适用市场": [str], "原始分析": str
        }
    """
    if not _DASHSCOPE_API_KEY:
        return {
            "识别失败": True,
            "原因": "未配置 DASHSCOPE_API_KEY",
            "提示": "请手动输入商品品类后使用选品分析",
        }

    image_b64 = _encode_image_to_base64(image_path)
    if not image_b64:
        return {
            "识别失败": True,
            "原因": "图片文件不存在或读取失败",
            "提示": "请重新上传商品图",
        }

    req_text = f"\n用户选品要求：{requirements}" if requirements else ""

    try:
        from dashscope import MultiModalConversation

        messages = [{
            "role": "user",
            "content": [
                {"image": f"data:image/jpeg;base64,{image_b64}"},
                {"text": (
                    "你是一位跨境电商选品专家。请分析这张商品图片，用中文回答以下问题：\n"
                    "1. 这是什么品类？（从以下选择最接近的：电子产品、服装、家居、家居用品、美妆、宠物用品、"
                    "玻璃杯、水杯、玻璃制品、厨房用品、户外运动、玩具）\n"
                    "2. 产品名称是什么？\n"
                    "3. 材质和工艺是什么？\n"
                    "4. 设计风格是什么？（简约/复古/奢华/北欧/日式/美式/工业风等）\n"
                    "5. 适合在哪个跨境电商市场销售？（美国/欧盟/日本/东南亚）\n"
                    "6. 从图片中能看到哪些卖点？（列出3-5个关键卖点）\n"
                    f"{req_text}\n"
                    "请用以下格式输出，方便程序解析：\n"
                    "品类: xxx\n商品名: xxx\n材质: xxx\n风格: xxx\n适用市场: xxx\n卖点: xxx, xxx, xxx"
                )},
            ]
        }]

        response = MultiModalConversation.call(
            model="qwen-vl-plus",
            messages=messages,
            api_key=_DASHSCOPE_API_KEY,
        )

        raw_text = ""
        if response and response.output and response.output.choices:
            raw_text = response.output.choices[0].message.content[0].get("text", "")

        if not raw_text:
            return {"识别失败": True, "原因": "视觉模型未返回有效结果"}

        # 解析结构化字段
        parsed = _parse_vision_result(raw_text)
        parsed["原始分析"] = raw_text
        return parsed

    except ImportError:
        return {"识别失败": True, "原因": "dashscope 库未安装"}
    except Exception as e:
        logger.warning("[商品图选品] Qwen-VL 调用异常: %s", e)
        return {"识别失败": True, "原因": f"视觉分析异常: {str(e)[:100]}"}


def _parse_vision_result(text: str) -> Dict[str, Any]:
    """从 Qwen-VL 返回的文本中解析结构化字段。"""
    result = {"品类": "", "商品名": "", "材质": "", "风格": "", "适用市场": "", "卖点": []}

    field_map = {
        "品类": "品类",
        "商品名": "商品名",
        "材质": "材质",
        "风格": "风格",
        "适用市场": "适用市场",
        "卖点": "卖点",
    }

    for line in text.split("\n"):
        line = line.strip()
        for key, field in field_map.items():
            if line.startswith(f"{key}:") or line.startswith(f"{key}："):
                val = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                if field == "卖点":
                    result[field] = [v.strip() for v in val.replace("，", ",").split(",") if v.strip()]
                else:
                    result[field] = val

    return result


# ============ Agent 工具注册 ============

@tool("selection_by_image")
def 商品图选品分析(image_path: str, 选品要求: str = "", 目标市场: str = "美国") -> str:
    """上传商品图，AI 自动识别品类后跑全套选品分析。

    当用户上传了商品图并要求选品时调用此工具。
    自动用视觉模型识别图片中的品类、材质、风格，然后调用智能选品分析获取竞品数据。

    Args:
        image_path: 已上传的商品图路径（/uploads/xxx.jpg）
        选品要求: 用户附加的选品要求（如售价区间、目标利润率等）
        目标市场: 目标市场（如 美国、欧盟、日本、东南亚）

    Returns:
        合并的选品分析报告（图像识别 + 智能选品）
    """
    lines = ["## 商品图智能选品分析", ""]

    # 步骤1: 视觉识别
    lines.append("### 1. 商品图识别")
    lines.append(f"- 图片路径: {image_path}")

    analysis = analyze_product_image(image_path, 选品要求)

    if analysis.get("识别失败"):
        lines.append(f"- 识别状态: 失败（{analysis.get('原因')}）")
        if analysis.get("提示"):
            lines.append(f"- {analysis.get('提示')}")
        # 尝试从选品要求中推测品类
        if 选品要求:
            lines.append(f"- 将基于选品要求尝试匹配品类")
        return "\n".join(lines)

    detected_category = analysis.get("品类", "")
    lines.append(f"- 识别品类: {detected_category}")
    lines.append(f"- 商品名: {analysis.get('商品名', '未识别')}")
    lines.append(f"- 材质工艺: {analysis.get('材质', '未识别')}")
    lines.append(f"- 设计风格: {analysis.get('风格', '未识别')}")
    lines.append(f"- 适用市场: {analysis.get('适用市场', '未识别')}")

    selling_points = analysis.get("卖点", [])
    if selling_points:
        lines.append(f"- 图片卖点: {' | '.join(selling_points)}")

    # 选品要求
    if 选品要求:
        lines.append(f"- 用户要求: {选品要求}")

    # 步骤2: 根据识别结果跑选品
    if detected_category:
        lines.append("")
        lines.append(f"### 2. 智能选品分析（品类: {detected_category}）")

        from 工具集.智能筛品 import 智能选品分析

        # 如果用户指定了市场，用用户指定的；否则用视觉识别的
        market = 目标市场
        if analysis.get("适用市场") and not 目标市场:
            market = analysis["适用市场"]

        selection_result = 智能选品分析.invoke({
            "品类": detected_category,
            "目标市场": market,
            "最低利润率": 0.15,
        })

        lines.append(selection_result)

        # 步骤3: 痛点分析
        lines.append("")
        lines.append(f"### 3. 竞品痛点分析")

        from 工具集.痛点拆解 import 痛点分析

        pain_result = 痛点分析.invoke({
            "品类": detected_category,
            "目标市场": market,
        })

        lines.append(pain_result)

        # 步骤4: 视觉卖点与开发方向
        if selling_points:
            lines.append("")
            lines.append("### 4. 视觉卖点与开发方向")
            lines.append(f"- 材质工艺: {analysis.get('材质', '未知')}")
            lines.append(f"- 设计风格: {analysis.get('风格', '未知')}")
            lines.append(f"- 识别卖点:")
            for sp in selling_points:
                lines.append(f"  - {sp}")
            lines.append("")
            lines.append("基于视觉识别的差异化方向：")
            lines.append(f"- 主图拍摄建议：突出{analysis.get('材质', '产品')}的质感细节，{analysis.get('风格', '')}风格布景")
            lines.append(f"- 详情页重点：围绕识别到的卖点做分层展示（{'/'.join(selling_points[:3])}）")
            lines.append(f"- 包装升级：匹配{analysis.get('风格', '简约')}定位，礼盒装提升客单价感知")
            if analysis.get('适用市场'):
                lines.append(f"- 市场适配：{analysis.get('适用市场')}市场偏好{analysis.get('风格', '')}风格，Listing可做本地化优化")

        # 步骤5: 关税分析
        from 工具集.关税查询 import 查询关税
        # 品类映射：视觉识别的品类 → 关税数据库品类
        _tariff_map = {"玻璃杯": "玻璃制品", "水杯": "玻璃制品", "电子产品": "电子产品",
                       "服装": "服装", "家居": "家居用品", "美妆": "美妆", "宠物用品": "宠物用品"}
        _tariff_cat = _tariff_map.get(detected_category, detected_category)
        lines.append("")
        lines.append(f"### 5. 关税分析（{market} + {_tariff_cat}）")
        tariff_result = 查询关税.invoke({
            "目的国": market,
            "商品类别": _tariff_cat,
        })
        lines.append(tariff_result)

        # 步骤6: 物流时效
        from 工具集.物流时效 import 物流时效查询
        lines.append("")
        lines.append(f"### 6. 物流时效（中国→{market}）")
        for _mode in ["海运", "空运", "快递"]:
            logistics_result = 物流时效查询.invoke({
                "发货地": "中国",
                "目的国": market if market != "欧盟" else "欧洲",
                "物流方式": _mode,
            })
            lines.append(logistics_result)

        # 步骤7: 利润测算（基于选品分析中的代表商品）
        from 工具集.利润计算 import 利润计算
        from 工具集.数据采集 import fetch_rainforest_competitors
        lines.append("")
        lines.append("### 7. 利润测算（基于竞品中位价）")
        _comp_data = fetch_rainforest_competitors(detected_category, market)
        _prices = []
        if _comp_data:
            for c in _comp_data.get("竞品列表", []):
                p = c.get("价格")
                if isinstance(p, (int, float)) and p > 0:
                    _prices.append(p)
        if _prices:
            _median_price = sorted(_prices)[len(_prices)//2]
            _estimated_cost = round(_median_price * 0.35, 2)
            _shipping = 4.0
            _tariff_rate = 0.07 if "美国" in market else (0.12 if "欧盟" in market else 0.05)
            _tariff_amt = round(_median_price * _tariff_rate, 2)
            profit_result = 利润计算.invoke({
                "售价": _median_price,
                "采购成本": _estimated_cost,
                "运费": _shipping,
                "关税": _tariff_amt,
            })
            lines.append(f"- 代表商品中位售价: ${_median_price}")
            lines.append(f"- 预估采购成本(35%): ${_estimated_cost}")
            lines.append(f"- 预估单件运费: ${_shipping}")
            lines.append(f"- 预估关税({_tariff_rate*100:.0f}%): ${_tariff_amt}")
            lines.append(profit_result)
        else:
            lines.append("（竞品价格数据不足，跳过利润测算）")

    else:
        lines.append("")
        lines.append("未识别到品类，请手动指定品类后重新选品。")

    return "\n".join(lines)
