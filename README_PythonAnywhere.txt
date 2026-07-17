PythonAnywhere 部署指南
=======================

1. 注册账号
   访问 https://www.pythonanywhere.com 注册免费账号

2. 上传文件
   - 登录后进入 Dashboard
   - 点击顶部 "Files" 标签
   - 点击 "Upload a file" 按钮
   - 上传所有文件（app.py, database.py, requirements.txt, wsgi.py, templates/, static/ 等）

3. 创建虚拟环境（可选但推荐）
   - 点击顶部 "Consoles" 标签
   - 点击 "Bash" 创建一个新的 Bash 控制台
   - 执行以下命令：
     ```
     mkvirtualenv --python=/usr/bin/python3.10 qr-order-env
     workon qr-order-env
     pip install -r requirements.txt
     ```

4. 配置 Web App
   - 点击顶部 "Web" 标签
   - 点击 "Add a new web app"
   - 选择 "Manual configuration" (Python 3.10)
   - 在 "Source code" 部分，设置路径为你的项目目录（如 /home/你的用户名/qr-order-system）
   - 在 "WSGI configuration file" 部分，编辑 wsgi.py 文件，确保内容如下：
     ```
     import sys
     import os
     path = '/home/你的用户名/qr-order-system'
     if path not in sys.path:
         sys.path.append(path)
     from app import app as application
     ```
   - 保存配置

5. 设置虚拟环境（如果创建了）
   - 在 Web App 配置页面，找到 "Virtualenv" 部分
   - 输入虚拟环境路径（如 /home/你的用户名/.virtualenvs/qr-order-env）

6. 重启应用
   - 点击 "Reload 你的用户名.pythonanywhere.com"

7. 访问网站
   - 顾客端：https://你的用户名.pythonanywhere.com
   - 管理后台：https://你的用户名.pythonanywhere.com/admin

注意事项：
- 免费套餐不支持自定义域名
- 每月有10万次请求限制
- 应用闲置时会休眠，访问时需等待约30秒启动
- SQLite 数据库文件在 /home/你的用户名/qr-order-system/qr_order.db