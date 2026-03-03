#!/bin/bash

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Starting Matcha AI...${NC}"

# 如果参数是 dev，或者 frontend/out 不存在，则构建前端
if [ "$1" == "dev" ] || [ ! -d "frontend/out" ]; then
    echo -e "${GREEN}Building frontend...${NC}"
    cd frontend && npm install && npm run build && cd ..
fi

# 获取项目根目录的绝对路径
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_EXE=$( [ -d "$ROOT_DIR/venv" ] && echo "$ROOT_DIR/venv/bin/python3" || echo "python3" )

echo -e "${GREEN}Running server at http://localhost:8501${NC}"
cd "$ROOT_DIR/backend" && "$PYTHON_EXE" entry_server.py
