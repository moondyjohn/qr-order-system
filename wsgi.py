import sys
import os

# 添加项目路径到系统路径
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

# 导入 Flask 应用
from app import app as application

# 如果需要，可以在这里进行其他配置
if __name__ == "__main__":
    application.run()