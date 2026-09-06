# -*- coding: utf-8 -*-
"""关税查询工具测试：官方税率表 / 别名归一 / 免税额度 / 关税计算 / 数据库优先级。

覆盖点（面试讲解重点）：
1. 税率来自各国海关官方税率表，可精确断言具体数值（零幻觉验证）；
2. 市场/品类别名归一（usa→美国、3c→电子产品）；
3. de minimis 免税额度内免征，超出按 CIF 计征；
4. MySQL 缓存优先于内置表，DB 不可用时静默降级到内置表。
"""

from 工具集.关税查询 import 查询关税, TARIFF_DB, DE_MINIMIS


def _查(目的国, 商品类别, 货值=0.0, 运费=0.0, 保险费=0.0):
    # @tool 装饰后 .func 是原始函数，直接调用绕开 schema 校验开销
    return 查询关税.func(目的国, 商品类别, 货值, 运费, 保险费)


# ============ 内置税率表自检 ============

class Test税率表完整性:
    def test_每条规则字段齐全(self):
        for (country, cat), rule in TARIFF_DB.items():
            assert country, f"空国家: {rule}"
            assert 0.0 <= rule["tariff_rate"] <= 2.0, f"{country}-{cat} 税率异常: {rule['tariff_rate']}"
            assert rule["hs_code"]
            assert rule["source"]

    def test_主要市场全覆盖(self):
        markets = {c for c, _ in TARIFF_DB}
        assert {"美国", "欧盟", "日本", "英国", "东南亚"} <= markets

    def test_免税额度与市场一致(self):
        assert DE_MINIMIS["美国"] == 800.0
        assert DE_MINIMIS["欧盟"] == 0.0


# ============ 查询与计算 ============

class Test关税查询:
    def test_美国服装税率32(self, db_offline):
        r = _查("美国", "服装")
        assert "32.00%" in r
        assert "6110.30.3059" in r
        assert "USITC" in r

    def test_别名归一_usa_3c(self, db_offline):
        # usa → 美国，3c → 电子产品，零关税
        r = _查("usa", "3c")
        assert "0.00%" in r

    def test_别名归一_大小写与英文(self, db_offline):
        r = _查("Japan", "apparel")
        assert "日本" in r
        assert "服装" in r

    def test_免税额度内免征(self, db_offline):
        # 美国服装 de minimis $800，货值 $500 → 免征
        r = _查("美国", "服装", 货值=500)
        assert "应缴关税: $0" in r
        assert "免征" in r

    def test_超额按CIF计征(self, db_offline):
        # 32% × (1000+100+50) = 368.00
        r = _查("美国", "服装", 货值=1000, 运费=100, 保险费=50)
        assert "$368.00" in r
        assert "$1,150.00" in r  # CIF 完税价格

    def test_欧盟无免税额度(self, db_offline):
        r = _查("欧盟", "服装", 货值=100)
        assert "免税额度: 无" in r
        assert "$12.00" in r  # 12% × 100

    def test_日本服装91税率(self, db_offline):
        r = _查("日本", "服装")
        assert "9.10%" in r

    def test_未覆盖组合给出行外建议(self, db_offline):
        r = _查("美国", "3D打印机")
        assert "未查询到" in r
        assert "mofcom" in r  # 引导到商务部查询


# ============ 数据库优先级 ============

class Test数据库优先级:
    def test_DB命中优先于内置表(self, monkeypatch):
        from 测试.conftest import patch_db
        # DB 缓存里美国服装税率 99%（故意不同于内置 32%，验证优先级）
        patch_db(monkeypatch, plan=[
            ("FROM tariff_rule", [
                {"hs_code": "9999.99.9999", "tariff_rate": 0.99, "note": "数据库测试规则"},
            ]),
        ])
        r = _查("美国", "服装")
        assert "99.00%" in r
        assert "数据库缓存" in r

    def test_DB离线降级到内置表(self, db_offline):
        # MySQL 不可用（get_cursor yield None）→ 用内置官方税率表
        r = _查("美国", "鞋类")
        assert "37.50%" in r

    def test_DB未命中降级到内置表(self, monkeypatch):
        from 测试.conftest import patch_db
        # DB 可用但查不到该组合（fetchone 返回 None）→ 内置表
        patch_db(monkeypatch, plan=[])
        r = _查("美国", "服装")
        assert "32.00%" in r
        assert "USITC" in r
