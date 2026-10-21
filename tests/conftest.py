"""功能：为本项目pytest提供工作区内的独立临时目录。
输入：pytest测试请求；输出：每个测试独占的临时路径。
流程：加入源码搜索路径，再以UUID创建临时目录；注意：避免Windows受限令牌下pytest的0700目录权限问题，保留小型测试产物便于复核。
"""
from pathlib import Path
import sys
from uuid import uuid4
import pytest

# 测试与源码分离后，仅在测试会话中显式加入源码目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))


@pytest.fixture
def tmp_path():
    """创建继承工作区权限的测试目录，不读取或清理用户原有临时目录。"""
    path = PROJECT_ROOT / "outputs" / "test_artifacts" / uuid4().hex
    path.mkdir(parents=True)
    return path
