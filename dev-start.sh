#!/bin/bash
# ShadowPartner 本地开发环境一键启动脚本
# 使用 tmux 在单个窗口中显示所有服务的日志

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检查依赖
check_dependencies() {
    echo -e "${GREEN}检查依赖...${NC}"

    if ! command -v tmux &> /dev/null; then
        echo -e "${RED}错误: 未找到 tmux${NC}"
        echo "请安装 tmux: sudo apt-get install tmux"
        exit 1
    fi

    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}错误: 未找到 python3${NC}"
        exit 1
    fi

    if ! command -v uv &> /dev/null; then
        echo -e "${YELLOW}警告: 未找到 uv，将使用 pip${NC}"
    fi
}

# 初始化配置文件
init_config() {
    echo -e "${GREEN}初始化配置文件...${NC}"

    # Backend .env
    if [ ! -f "$PROJECT_ROOT/backend/.env" ]; then
        cp "$PROJECT_ROOT/backend/.env.example" "$PROJECT_ROOT/backend/.env"
        echo -e "${YELLOW}已创建 backend/.env，请根据需要修改${NC}"
    fi

    # Worker .env
    if [ ! -f "$PROJECT_ROOT/worker/.env" ]; then
        cp "$PROJECT_ROOT/worker/.env.example" "$PROJECT_ROOT/worker/.env"
        echo -e "${YELLOW}已创建 worker/.env，请根据需要修改${NC}"
    fi

    # 创建数据目录
    mkdir -p "$PROJECT_ROOT/data/storage"
    mkdir -p "$PROJECT_ROOT/data/cache/audio"
}

# 启动服务
start_services() {
    local SESSION="shadowpartner"

    # 检查是否已有同名 session
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo -e "${YELLOW}Session '$SESSION' 已存在${NC}"
        read -p "是否关闭旧 session 并重新启动? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            tmux kill-session -t "$SESSION"
        else
            echo "使用现有 session: tmux attach -t $SESSION"
            exit 0
        fi
    fi

    echo -e "${GREEN}启动 tmux session: $SESSION${NC}"

    # 创建新 session
    tmux new-session -d -s "$SESSION" -n "ShadowPartner"

    # 窗格布局: 上半部分是 backend，下半部分左右分割是 frontend 和 worker

    # 0: backend (先启动，占满整个窗口)
    tmux send-keys -t "$SESSION:0.0" "cd '$PROJECT_ROOT/backend'" C-m
    if command -v uv &> /dev/null; then
        tmux send-keys -t "$SESSION:0.0" "uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000" C-m
    else
        tmux send-keys -t "$SESSION:0.0" "python main.py --port 8000" C-m
    fi

    # 垂直分割，创建下半部分 (pane 1)
    tmux split-window -v -t "$SESSION:0.0"

    # 1: frontend (下半部分先启动 frontend)
    tmux send-keys -t "$SESSION:0.1" "cd '$PROJECT_ROOT/frontend'" C-m
    tmux send-keys -t "$SESSION:0.1" "python3 -m http.server 3000" C-m

    # 水平分割下半部分，创建 worker (pane 2)
    tmux split-window -h -t "$SESSION:0.1"

    # 2: worker (右下角)
    tmux send-keys -t "$SESSION:0.2" "cd '$PROJECT_ROOT/worker'" C-m
    if command -v uv &> /dev/null; then
        tmux send-keys -t "$SESSION:0.2" "uv run python main.py" C-m
    else
        tmux send-keys -t "$SESSION:0.2" "python main.py" C-m
    fi

    # 调整窗格大小: backend (pane 0) 占上半部分
    tmux resize-pane -t "$SESSION:0.0" -U 20  # 向上扩大 20 行

    # 添加状态栏显示服务信息
    tmux set-option -t "$SESSION" status-left " ShadowPartner Dev "
    tmux set-option -t "$SESSION" status-right " %H:%M:%S "
    tmux set-option -t "$SESSION" pane-border-status top
    tmux set-option -t "$SESSION" pane-border-format " #{pane_index} #{pane_title} "

    # 绑定快捷键: Ctrl+X 停止所有服务并退出 session
    tmux bind-key -T root C-x kill-session

    # 显示快捷键提示
    tmux display-message "按 Ctrl+X 停止所有服务 | Ctrl+b+d 分离 | Ctrl+b+方向键 切换窗格"

    echo -e "${GREEN}服务启动中...${NC}"
    sleep 2

    # 连接到 session
    tmux attach-session -t "$SESSION"
}

# 显示帮助
show_help() {
    cat << EOF
ShadowPartner 本地开发环境启动脚本

用法:
    $0 [选项]

选项:
    -h, --help          显示此帮助信息
    -s, --status        显示 tmux session 状态
    -l, --logs          显示日志 (附加到现有 session)
    -k, --kill          停止所有服务
    -r, --restart       重启所有服务
    --no-tmux           不使用 tmux，简单启动 (日志输出到文件)

服务端口:
    Backend:  http://localhost:8000
    Frontend: http://localhost:3000
    API Docs: http://localhost:8000/docs

配置文件:
    backend/.env    - 后端配置
    worker/.env     - Worker 配置

EOF
}

# 停止服务
kill_services() {
    local SESSION="shadowpartner"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo -e "${YELLOW}停止服务...${NC}"
        tmux kill-session -t "$SESSION"
        echo -e "${GREEN}服务已停止${NC}"
    else
        echo -e "${YELLOW}没有运行中的服务${NC}"
    fi
}

# 显示状态
show_status() {
    local SESSION="shadowpartner"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo -e "${GREEN}服务正在运行${NC}"
        tmux list-sessions | grep "$SESSION"
        echo ""
        echo "服务地址:"
        echo "  Backend:  http://localhost:8000"
        echo "  Frontend: http://localhost:3000"
        echo "  API Docs: http://localhost:8000/docs"
        echo ""
        echo "附加到 session: tmux attach -t $SESSION"
    else
        echo -e "${YELLOW}服务未运行${NC}"
    fi
}

# 不使用 tmux 的简单启动
simple_start() {
    echo -e "${GREEN}简单启动模式 (日志输出到 data/logs/)${NC}"
    mkdir -p "$PROJECT_ROOT/data/logs"

    # 启动 backend
    echo "启动 Backend..."
    cd "$PROJECT_ROOT/backend"
    if command -v uv &> /dev/null; then
        uv run uvicorn main:app --host 0.0.0.0 --port 8000 \
            > "$PROJECT_ROOT/data/logs/backend.log" 2>&1 &
    else
        python main.py --port 8000 \
            > "$PROJECT_ROOT/data/logs/backend.log" 2>&1 &
    fi
    echo $! > "$PROJECT_ROOT/data/logs/backend.pid"

    # 启动 frontend
    echo "启动 Frontend..."
    cd "$PROJECT_ROOT/frontend"
    python3 -m http.server 3000 \
        > "$PROJECT_ROOT/data/logs/frontend.log" 2>&1 &
    echo $! > "$PROJECT_ROOT/data/logs/frontend.pid"

    # 启动 worker
    echo "启动 Worker..."
    cd "$PROJECT_ROOT/worker"
    if command -v uv &> /dev/null; then
        uv run python main.py \
            > "$PROJECT_ROOT/data/logs/worker.log" 2>&1 &
    else
        python main.py \
            > "$PROJECT_ROOT/data/logs/worker.log" 2>&1 &
    fi
    echo $! > "$PROJECT_ROOT/data/logs/worker.pid"

    echo -e "${GREEN}所有服务已启动${NC}"
    echo ""
    echo "服务地址:"
    echo "  Backend:  http://localhost:8000"
    echo "  Frontend: http://localhost:3000"
    echo "  API Docs: http://localhost:8000/docs"
    echo ""
    echo "查看日志:"
    echo "  tail -f data/logs/backend.log"
    echo "  tail -f data/logs/frontend.log"
    echo "  tail -f data/logs/worker.log"
    echo ""
    echo "停止服务: $0 --kill"
}

# 主函数
main() {
    case "${1:-}" in
        -h|--help)
            show_help
            ;;
        -s|--status)
            show_status
            ;;
        -l|--logs)
            tmux attach-session -t "shadowpartner" 2>/dev/null || echo "服务未运行"
            ;;
        -k|--kill)
            kill_services
            ;;
        -r|--restart)
            kill_services
            sleep 1
            check_dependencies
            init_config
            start_services
            ;;
        --no-tmux)
            check_dependencies
            init_config
            simple_start
            ;;
        *)
            check_dependencies
            init_config
            start_services
            ;;
    esac
}

main "$@"
