"""DXF 数据提取服务（向后兼容门面）。

所有实现已拆分至 services.dxf 包，此文件仅做 re-export
以保持 ``from services.dxf_service import ...`` 路径不变。
"""

from services.dxf import *  # noqa: F401, F403
