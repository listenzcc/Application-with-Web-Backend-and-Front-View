"""临时预览服务：清掉鉴权中间件，把页面放出来给无头浏览器截图。

用完即删。main.py 里全是相对路径（'conf/project.yml'、'static/...'），
所以 CWD 必须是项目根目录，脚本本身放在 python/ 下让 import 生效。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.chdir(ROOT)
sys.path.insert(0, str(HERE))

import main  # noqa: E402
from nicegui import app, ui  # noqa: E402

# 鉴权是中间件，清掉就把页面放出来了（这是临时预览服务，别在正式服务里做）
app.user_middleware.clear()

SESSION = (sys.argv[1] if len(sys.argv) > 1 else
           '2026-10-12-11-02-29-a067e668-1098-4dfc-91b2-282a57c69e42')
print('preview session:', SESSION, flush=True)

ui.run(port=8123, reload=False, show=False, storage_secret='abcdefg',
       title='preview', favicon='./static/favicon/favicon.ico')
