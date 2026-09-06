# -*- coding: utf-8 -*-
"""文件安全测试：图片路径约束与上传校验（安全整改回归用例）。

覆盖点：
1. safe_resolve_upload_path：拒绝绝对路径 / 目录穿越 / 盘符路径；
   接受 /uploads/<名> 与裸文件名，且解析结果锁定在 UPLOAD_DIR 内；
2. validate_image_upload：扩展名白名单、大小上限、文件头魔数；
3. 业务模块路径解析收口：商品图选品 _resolve_image_path 不再吃任意本地路径。
"""
import pytest

from 基础设施.文件安全 import (
    UPLOAD_DIR,
    MAX_IMAGE_BYTES,
    safe_resolve_upload_path,
    validate_image_upload,
    save_upload_image,
)


# ============ 路径约束 ============

class Test路径约束:
    def test_合法uploads路径(self):
        p = safe_resolve_upload_path("/uploads/product_1.jpg")
        assert p is not None
        assert p.parent.resolve() == UPLOAD_DIR.resolve()
        assert p.name == "product_1.jpg"

    def test_合法裸文件名(self):
        p = safe_resolve_upload_path("product_1.jpg")
        assert p is not None
        assert p.name == "product_1.jpg"

    @pytest.mark.parametrize("bad", [
        "C:/Users/houhou/.env",            # Windows 绝对路径
        "C:\\Users\\houhou\\.env",         # 盘符 + 反斜杠
        "/etc/passwd",                      # 其他目录绝对路径
        "../.env",                          # 目录穿越
        "/uploads/../../.env",             # 借 uploads 前缀穿越
        "uploads/../../secret.txt",
        "sub/dir/x.jpg",                    # 子目录路径一律不允许
        "",                                 # 空
        None,                               # 非法类型
    ])
    def test_非法路径一律拒绝(self, bad):
        assert safe_resolve_upload_path(bad) is None

    def test_解析结果不会越出上传目录(self):
        # 构造能骗过前缀判断但 resolve 后越界的输入
        p = safe_resolve_upload_path("/uploads/../静态资源/images/x.png")
        assert p is None


# ============ 上传校验 ============

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPG = b"\xff\xd8\xff" + b"\x00" * 32


class Test上传校验:
    def test_png通过(self):
        ok, err = validate_image_upload(_PNG, "a.png")
        assert ok and err == ""

    def test_jpg通过(self):
        ok, err = validate_image_upload(_JPG, "a.jpg")
        assert ok and err == ""

    def test_扩展名白名单(self):
        # 内容是图片但扩展名是 html → 拒（防存储型 XSS）
        ok, err = validate_image_upload(_PNG, "shell.html")
        assert not ok
        assert "格式" in err

    def test_内容魔数不符拒绝(self):
        ok, err = validate_image_upload(b"<html>fake</html>", "a.png")
        assert not ok
        assert "有效图片" in err

    def test_大小上限(self):
        ok, err = validate_image_upload(_PNG + b"\x00" * MAX_IMAGE_BYTES, "big.png")
        assert not ok
        assert "大小" in err

    def test_空内容拒绝(self):
        ok, err = validate_image_upload(b"", "a.png")
        assert not ok

    def test_save不合法内容抛ValueError(self):
        with pytest.raises(ValueError):
            save_upload_image(b"<svg onload=alert(1)>", "x.svg")


# ============ 业务模块收口 ============

class Test业务模块路径收口:
    def test_商品图选品拒绝任意本地路径(self):
        from 工具集.商品图选品 import _resolve_image_path
        # 项目里真实存在的敏感文件，绝不允许被解析成功
        assert _resolve_image_path("config.py") is None
        assert _resolve_image_path(".env") is None

    def test_商品图选品uploads内文件可解析(self, tmp_path):
        import 工具集.商品图选品 as m
        from 基础设施 import 文件安全
        target = 文件安全.UPLOAD_DIR / "_test_case_.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_JPG)
        try:
            p = m._resolve_image_path("/uploads/_test_case_.jpg")
            assert p is not None and p.is_file()
        finally:
            target.unlink(missing_ok=True)
